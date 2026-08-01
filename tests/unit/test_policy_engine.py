from datetime import UTC, datetime, timedelta

from apps.agent_api.services.policy import (
    PolicyRejectionCode,
    PolicyUsage,
    evaluate_payment_policy,
)
from apps.agent_api.tools.resolve_intent import (
    SOLANA_DEVNET_USDC_MINT,
    resolve_payment_intent,
)
from packages.schemas import PaymentIntent, SpendingPolicy

NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)
RECIPIENT = "FvJ8k8HhXp4a3zQyFMZd4FvEqcYdYE7gSZWxrEBRfBsB"
REFERENCE = "11111111111111111111111111111111"


def make_intent(amount: str = "1") -> PaymentIntent:
    return resolve_payment_intent(
        f"solana:{RECIPIENT}?amount={amount}&spl-token={SOLANA_DEVNET_USDC_MINT}"
        f"&reference={REFERENCE}&label=demo-merchant"
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


def evaluate(
    intent: PaymentIntent,
    policy: SpendingPolicy,
    *,
    merchant: str | None = "demo-merchant",
    usage: PolicyUsage | None = None,
):
    return evaluate_payment_policy(
        intent,
        policy,
        verified_merchant_id=merchant,
        network_fee_lamports=5_000,
        slippage_bps=0,
        usage=usage or PolicyUsage(),
        now=NOW,
    )


def test_allows_request_within_every_policy_limit() -> None:
    result = evaluate(make_intent(), make_policy())

    assert result.allowed
    assert result.rejection_codes == ()


def test_rejects_per_transaction_and_daily_budget_excess() -> None:
    result = evaluate(
        make_intent("1.000001"),
        make_policy(),
        usage=PolicyUsage(daily_spent_atomic=4_000_000),
    )

    assert PolicyRejectionCode.AMOUNT_EXCEEDS_TRANSACTION_LIMIT in result.rejection_codes
    assert PolicyRejectionCode.DAILY_BUDGET_EXCEEDED in result.rejection_codes


def test_display_label_is_not_merchant_identity() -> None:
    result = evaluate(make_intent(), make_policy(), merchant=None)

    assert not result.allowed
    assert result.rejection_codes == (PolicyRejectionCode.MERCHANT_NOT_ALLOWED,)


def test_rejects_fee_slippage_and_transaction_count_limits() -> None:
    result = evaluate_payment_policy(
        make_intent(),
        make_policy(),
        verified_merchant_id="demo-merchant",
        network_fee_lamports=100_001,
        slippage_bps=51,
        usage=PolicyUsage(transaction_count=10),
        now=NOW,
    )

    assert PolicyRejectionCode.DAILY_TRANSACTION_LIMIT_EXCEEDED in result.rejection_codes
    assert PolicyRejectionCode.NETWORK_FEE_EXCEEDED in result.rejection_codes
    assert PolicyRejectionCode.SLIPPAGE_EXCEEDED in result.rejection_codes


def test_expired_policy_is_rejected() -> None:
    result = evaluate(make_intent(), make_policy(expires_at=NOW))

    assert result.rejection_codes == (PolicyRejectionCode.POLICY_EXPIRED,)


def test_rejects_unallowed_network_and_mint() -> None:
    result = evaluate(
        make_intent(),
        make_policy(
            allowed_networks=["solana:mainnet"],
            allowed_asset_mints=["DifferentMint"],
            budget_asset_mint="DifferentMint",
        ),
    )

    assert PolicyRejectionCode.NETWORK_NOT_ALLOWED in result.rejection_codes
    assert PolicyRejectionCode.ASSET_NOT_ALLOWED in result.rejection_codes
    assert PolicyRejectionCode.BUDGET_ASSET_MISMATCH in result.rejection_codes
