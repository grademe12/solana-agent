from datetime import UTC, datetime, timedelta

from apps.agent_api.services import (
    AttemptStatus,
    GuardedMockCheckout,
    InMemoryPaymentLedger,
    MockSolanaGateway,
    MockTransferPlan,
    MockWallet,
)
from apps.agent_api.tools.resolve_intent import SOLANA_DEVNET_USDC_MINT
from packages.schemas import PaymentIntent, SpendingPolicy

NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)
PAYER = "11111111111111111111111111111111"
RECIPIENT = "FvJ8k8HhXp4a3zQyFMZd4FvEqcYdYE7gSZWxrEBRfBsB"
REFERENCE = "SysvarC1ock11111111111111111111111111111111"
PAYLOAD = (
    f"solana:{RECIPIENT}?amount=1&spl-token={SOLANA_DEVNET_USDC_MINT}"
    f"&reference={REFERENCE}&label=Demo%20Merchant"
)


def make_policy(**overrides: object) -> SpendingPolicy:
    data: dict[str, object] = {
        "policy_id": "demo-policy",
        "user_id": "demo-user",
        "enabled": True,
        "allowed_networks": ["solana:devnet"],
        "allowed_asset_mints": [SOLANA_DEVNET_USDC_MINT],
        "allowed_merchants": ["demo-merchant"],
        "budget_asset_mint": SOLANA_DEVNET_USDC_MINT,
        "budget_decimals": 6,
        "max_per_transaction_atomic": 1_000_000,
        "max_daily_atomic": 5_000_000,
        "max_transactions_per_day": 10,
        "max_network_fee_lamports": 100_000,
        "max_slippage_bps": 50,
        "expires_at": NOW + timedelta(days=1),
    }
    data.update(overrides)
    return SpendingPolicy.model_validate(data)


def make_checkout(
    *, token_balance: int = 10_000_000, sol_lamports: int = 1_000_000
) -> tuple[GuardedMockCheckout, MockWallet, MockSolanaGateway]:
    wallet = MockWallet(
        public_key=PAYER,
        token_balances={SOLANA_DEVNET_USDC_MINT: token_balance},
        sol_lamports=sol_lamports,
    )
    gateway = MockSolanaGateway(fee_lamports=5_000)
    checkout = GuardedMockCheckout(
        ledger=InMemoryPaymentLedger(),
        wallet=wallet,
        gateway=gateway,
    )
    return checkout, wallet, gateway


def run(checkout: GuardedMockCheckout, payload: str = PAYLOAD):
    return checkout.run(
        payload,
        make_policy(),
        session_id="demo-session",
        verified_merchant_id="demo-merchant",
        now=NOW,
    )


def test_mock_checkout_completes_all_guarded_stages() -> None:
    checkout, wallet, gateway = make_checkout()

    result = run(checkout)

    assert result.status is AttemptStatus.CONFIRMED
    assert result.failure_code is None
    assert result.receipt is not None
    assert result.receipt.mock is True
    assert result.receipt.explorer_url is None
    assert result.receipt.recipient == RECIPIENT
    assert result.receipt.mint == SOLANA_DEVNET_USDC_MINT
    assert result.receipt.amount_atomic == 1_000_000
    assert result.receipt.reference == REFERENCE
    assert gateway.submit_count == 1
    assert wallet.snapshot().token_balances[SOLANA_DEVNET_USDC_MINT] == 9_000_000
    assert wallet.snapshot().sol_lamports == 995_000


def test_duplicate_intent_returns_receipt_without_resubmission() -> None:
    checkout, wallet, gateway = make_checkout()

    first = run(checkout)
    second = checkout.run(
        PAYLOAD,
        make_policy(),
        session_id="different-session",
        verified_merchant_id="demo-merchant",
        now=NOW,
    )

    assert first.status is AttemptStatus.CONFIRMED
    assert second.status is AttemptStatus.CONFIRMED
    assert second.duplicate is True
    assert second.receipt == first.receipt
    assert gateway.submit_count == 1
    assert wallet.snapshot().token_balances[SOLANA_DEVNET_USDC_MINT] == 9_000_000


def test_policy_rejection_never_reaches_submission() -> None:
    checkout, wallet, gateway = make_checkout()
    initial = wallet.snapshot()

    result = checkout.run(
        PAYLOAD,
        make_policy(max_per_transaction_atomic=500_000),
        session_id="demo-session",
        verified_merchant_id="demo-merchant",
        now=NOW,
    )

    assert result.status is AttemptStatus.REJECTED
    assert "amount_exceeds_transaction_limit" in result.attempt.policy_rejection_codes
    assert gateway.submit_count == 0
    assert wallet.snapshot() == initial


def test_insufficient_balance_fails_before_submission_and_releases_reservation() -> None:
    checkout, wallet, gateway = make_checkout(token_balance=999_999)
    initial = wallet.snapshot()

    result = run(checkout)

    assert result.status is AttemptStatus.FAILED
    assert result.failure_code == "insufficient_balance"
    assert gateway.submit_count == 0
    assert wallet.snapshot() == initial


class TamperingGateway(MockSolanaGateway):
    def build_transfer(self, intent: PaymentIntent, *, payer: str) -> MockTransferPlan:
        plan = super().build_transfer(intent, payer=payer)
        return MockTransferPlan(
            network=plan.network,
            payer=plan.payer,
            recipient=PAYER,
            mint=plan.mint,
            amount_atomic=plan.amount_atomic,
            decimals=plan.decimals,
            reference=plan.reference,
            fee_lamports=plan.fee_lamports,
        )


def test_tampered_recipient_is_rejected_before_submission() -> None:
    wallet = MockWallet(
        public_key=PAYER,
        token_balances={SOLANA_DEVNET_USDC_MINT: 10_000_000},
        sol_lamports=1_000_000,
    )
    gateway = TamperingGateway()
    checkout = GuardedMockCheckout(
        ledger=InMemoryPaymentLedger(),
        wallet=wallet,
        gateway=gateway,
    )

    result = run(checkout)

    assert result.status is AttemptStatus.FAILED
    assert result.failure_code == "transaction_plan_mismatch"
    assert gateway.submit_count == 0


def test_base_request_is_rejected_without_mock_submission() -> None:
    checkout, _, gateway = make_checkout()
    payload = "ethereum:0x1111111111111111111111111111111111111111@8453/transfer?value=1"

    result = run(checkout, payload)

    assert result.status is AttemptStatus.REJECTED
    assert gateway.submit_count == 0

