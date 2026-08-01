from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from packages.schemas import SpendingPolicy


def make_policy(**overrides: object) -> SpendingPolicy:
    data: dict[str, object] = {
        "policy_id": "default-demo-policy",
        "user_id": "demo-user",
        "enabled": True,
        "allowed_networks": ["solana:devnet"],
        "allowed_asset_mints": ["DemoUsdcMint"],
        "allowed_merchants": ["demo-merchant"],
        "budget_asset_mint": "DemoUsdcMint",
        "budget_decimals": 6,
        "max_per_transaction_atomic": 1_000_000,
        "max_daily_atomic": 5_000_000,
        "max_transactions_per_day": 10,
        "max_network_fee_lamports": 100_000,
        "max_slippage_bps": 50,
        "expires_at": datetime(2026, 8, 4, tzinfo=UTC),
    }
    data.update(overrides)
    return SpendingPolicy.model_validate(data)


def test_policy_freezes_allowlists_and_preserves_atomic_limits() -> None:
    policy = make_policy()

    assert policy.allowed_networks == frozenset({"solana:devnet"})
    assert policy.max_per_transaction_atomic == 1_000_000
    assert policy.max_daily_atomic == 5_000_000


def test_daily_limit_cannot_be_lower_than_transaction_limit() -> None:
    with pytest.raises(ValidationError, match="daily limit"):
        make_policy(max_per_transaction_atomic=6_000_000)


def test_enabled_policy_requires_nonempty_allowlists() -> None:
    with pytest.raises(ValidationError, match="allowed_merchants"):
        make_policy(allowed_merchants=[])


def test_budget_mint_must_be_allowed() -> None:
    with pytest.raises(ValidationError, match="budget asset mint"):
        make_policy(budget_asset_mint="OtherMint")


def test_naive_policy_expiry_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        make_policy(expires_at=datetime(2026, 8, 4))
