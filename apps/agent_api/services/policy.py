"""Deterministic policy evaluation with no LLM or network dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from packages.schemas import PaymentIntent, SpendingPolicy


class PolicyRejectionCode(StrEnum):
    INTENT_NOT_EXECUTABLE = "intent_not_executable"
    POLICY_DISABLED = "policy_disabled"
    POLICY_EXPIRED = "policy_expired"
    NETWORK_NOT_ALLOWED = "network_not_allowed"
    ASSET_NOT_ALLOWED = "asset_not_allowed"
    MERCHANT_NOT_ALLOWED = "merchant_not_allowed"
    BUDGET_ASSET_MISMATCH = "budget_asset_mismatch"
    AMOUNT_EXCEEDS_TRANSACTION_LIMIT = "amount_exceeds_transaction_limit"
    DAILY_BUDGET_EXCEEDED = "daily_budget_exceeded"
    DAILY_TRANSACTION_LIMIT_EXCEEDED = "daily_transaction_limit_exceeded"
    NETWORK_FEE_EXCEEDED = "network_fee_exceeded"
    SLIPPAGE_EXCEEDED = "slippage_exceeded"


@dataclass(frozen=True, slots=True)
class PolicyUsage:
    """Atomic budget already committed within the current policy day."""

    daily_spent_atomic: int = 0
    daily_reserved_atomic: int = 0
    transaction_count: int = 0

    def __post_init__(self) -> None:
        if min(
            self.daily_spent_atomic,
            self.daily_reserved_atomic,
            self.transaction_count,
        ) < 0:
            raise ValueError("policy usage values cannot be negative")


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    allowed: bool
    rejection_codes: tuple[PolicyRejectionCode, ...]
    evaluated_at: datetime
    usage: PolicyUsage


def evaluate_payment_policy(
    intent: PaymentIntent,
    policy: SpendingPolicy,
    *,
    verified_merchant_id: str | None,
    network_fee_lamports: int,
    slippage_bps: int,
    usage: PolicyUsage,
    now: datetime,
) -> PolicyEvaluation:
    """Evaluate every relevant policy rule and return stable rejection codes."""

    if now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    if network_fee_lamports < 0:
        raise ValueError("network fee cannot be negative")
    if not 0 <= slippage_bps <= 10_000:
        raise ValueError("slippage must be between 0 and 10000 basis points")

    rejected: list[PolicyRejectionCode] = []

    if not intent.is_executable:
        rejected.append(PolicyRejectionCode.INTENT_NOT_EXECUTABLE)
    if not policy.enabled:
        rejected.append(PolicyRejectionCode.POLICY_DISABLED)
    if now >= policy.expires_at:
        rejected.append(PolicyRejectionCode.POLICY_EXPIRED)
    if intent.network not in policy.allowed_networks:
        rejected.append(PolicyRejectionCode.NETWORK_NOT_ALLOWED)

    mint = intent.asset.mint if intent.asset is not None else None
    if mint is None or mint not in policy.allowed_asset_mints:
        rejected.append(PolicyRejectionCode.ASSET_NOT_ALLOWED)
    if verified_merchant_id is None or verified_merchant_id not in policy.allowed_merchants:
        rejected.append(PolicyRejectionCode.MERCHANT_NOT_ALLOWED)

    amount = intent.amount
    if (
        amount is None
        or mint != policy.budget_asset_mint
        or amount.decimals != policy.budget_decimals
    ):
        rejected.append(PolicyRejectionCode.BUDGET_ASSET_MISMATCH)
    else:
        if amount.atomic > policy.max_per_transaction_atomic:
            rejected.append(PolicyRejectionCode.AMOUNT_EXCEEDS_TRANSACTION_LIMIT)
        projected_daily = (
            usage.daily_spent_atomic + usage.daily_reserved_atomic + amount.atomic
        )
        if projected_daily > policy.max_daily_atomic:
            rejected.append(PolicyRejectionCode.DAILY_BUDGET_EXCEEDED)

    if usage.transaction_count >= policy.max_transactions_per_day:
        rejected.append(PolicyRejectionCode.DAILY_TRANSACTION_LIMIT_EXCEEDED)
    if network_fee_lamports > policy.max_network_fee_lamports:
        rejected.append(PolicyRejectionCode.NETWORK_FEE_EXCEEDED)
    if slippage_bps > policy.max_slippage_bps:
        rejected.append(PolicyRejectionCode.SLIPPAGE_EXCEEDED)

    return PolicyEvaluation(
        allowed=not rejected,
        rejection_codes=tuple(rejected),
        evaluated_at=now,
        usage=usage,
    )

