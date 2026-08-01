import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.signature import Signature

from apps.agent_api.services.devnet_checkout import GuardedDevnetCheckout
from apps.agent_api.services.idempotency import AttemptStatus, InMemoryPaymentLedger
from apps.agent_api.services.solana_transfer import (
    PreparedSolanaTransfer,
    build_usdc_transfer_plan,
    compile_and_sign_transfer,
)
from apps.agent_api.settings import SOLANA_DEVNET_USDC_MINT
from packages.schemas import PaymentIntent, SpendingPolicy

NOW = datetime(2026, 8, 1, 16, tzinfo=UTC)
RECIPIENT = "FvJ8k8HhXp4a3zQyFMZd4FvEqcYdYE7gSZWxrEBRfBsB"
REFERENCE = "SysvarC1ock11111111111111111111111111111111"
PAYLOAD = (
    f"solana:{RECIPIENT}?amount=1&spl-token={SOLANA_DEVNET_USDC_MINT}"
    f"&reference={REFERENCE}"
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


class FakeDevnetGateway:
    def __init__(self) -> None:
        self.signer = Keypair()
        self.fee_lamports = 5_000
        self.simulation_succeeded = True
        self.confirmation_fails = False
        self.quote_count = 0
        self.prepare_count = 0
        self.submit_count = 0
        self.confirm_count = 0
        self._prepared: PreparedSolanaTransfer | None = None

    async def quote_fee(self, intent: PaymentIntent) -> int:
        self.quote_count += 1
        return self.fee_lamports

    async def prepare_and_simulate(self, intent: PaymentIntent) -> PreparedSolanaTransfer:
        self.prepare_count += 1
        plan = build_usdc_transfer_plan(intent, payer=self.signer.pubkey())
        blockhash = Hash.new_unique()
        transaction = compile_and_sign_transfer(
            plan,
            intent,
            signer=self.signer,
            recent_blockhash=blockhash,
        )
        self._prepared = PreparedSolanaTransfer(
            plan=plan,
            transaction=transaction,
            recent_blockhash=blockhash,
            last_valid_block_height=100,
            estimated_fee_lamports=self.fee_lamports,
            simulation_succeeded=self.simulation_succeeded,
            simulation_error=None if self.simulation_succeeded else "insufficient funds",
            simulation_logs=(),
            units_consumed=1,
        )
        return self._prepared

    async def submit_prepared(
        self,
        prepared: PreparedSolanaTransfer,
        intent: PaymentIntent,
    ) -> Signature:
        self.submit_count += 1
        return prepared.transaction.signatures[0]

    async def confirm_and_fetch(
        self,
        signature: Signature,
        *,
        last_valid_block_height: int,
    ) -> str:
        self.confirm_count += 1
        if self.confirmation_fails:
            raise RuntimeError("confirmation timeout")
        assert self._prepared is not None
        transaction = self._prepared.transaction
        return json.dumps(
            {
                "jsonrpc": "2.0",
                "result": {
                    "meta": {"err": None},
                    "transaction": [
                        base64.b64encode(bytes(transaction)).decode("ascii"),
                        "base64",
                    ],
                },
                "id": 1,
            }
        )


def run(checkout: GuardedDevnetCheckout, *, session_id: str = "demo-session"):
    return checkout.run(
        PAYLOAD,
        make_policy(),
        session_id=session_id,
        verified_merchant_id="demo-merchant",
        now=NOW,
    )


@pytest.mark.asyncio
async def test_guarded_devnet_checkout_confirms_exact_payment() -> None:
    gateway = FakeDevnetGateway()
    checkout = GuardedDevnetCheckout(ledger=InMemoryPaymentLedger(), gateway=gateway)

    result = await run(checkout)

    assert result.status is AttemptStatus.CONFIRMED
    assert result.receipt is not None
    assert result.receipt.amount_atomic == 1_000_000
    assert result.receipt.reference == REFERENCE
    assert gateway.prepare_count == 1
    assert gateway.submit_count == 1
    assert gateway.confirm_count == 1


@pytest.mark.asyncio
async def test_duplicate_intent_never_resubmits() -> None:
    gateway = FakeDevnetGateway()
    checkout = GuardedDevnetCheckout(ledger=InMemoryPaymentLedger(), gateway=gateway)

    first = await run(checkout)
    second = await run(checkout, session_id="another-session")

    assert first.status is AttemptStatus.CONFIRMED
    assert second.status is AttemptStatus.CONFIRMED
    assert second.duplicate is True
    assert second.receipt == first.receipt
    assert gateway.submit_count == 1


@pytest.mark.asyncio
async def test_policy_rejection_never_prepares_or_submits() -> None:
    gateway = FakeDevnetGateway()
    checkout = GuardedDevnetCheckout(ledger=InMemoryPaymentLedger(), gateway=gateway)

    result = await checkout.run(
        PAYLOAD,
        make_policy(max_per_transaction_atomic=500_000),
        session_id="demo-session",
        verified_merchant_id="demo-merchant",
        now=NOW,
    )

    assert result.status is AttemptStatus.REJECTED
    assert gateway.prepare_count == 0
    assert gateway.submit_count == 0


@pytest.mark.asyncio
async def test_simulation_failure_releases_reservation_without_submission() -> None:
    gateway = FakeDevnetGateway()
    gateway.simulation_succeeded = False
    checkout = GuardedDevnetCheckout(ledger=InMemoryPaymentLedger(), gateway=gateway)

    result = await run(checkout)

    assert result.status is AttemptStatus.FAILED
    assert result.failure_code == "simulation_failed"
    assert gateway.submit_count == 0


@pytest.mark.asyncio
async def test_confirmation_timeout_remains_submitted_and_cannot_resubmit() -> None:
    gateway = FakeDevnetGateway()
    gateway.confirmation_fails = True
    checkout = GuardedDevnetCheckout(ledger=InMemoryPaymentLedger(), gateway=gateway)

    first = await run(checkout)
    second = await run(checkout, session_id="another-session")

    assert first.status is AttemptStatus.SUBMITTED
    assert first.failure_code == "confirmation_pending"
    assert second.status is AttemptStatus.SUBMITTED
    assert second.duplicate is True
    assert gateway.submit_count == 1
