from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from solders.pubkey import Pubkey

from apps.agent_api.services.idempotency import (
    AttemptStatus,
    InMemoryPaymentLedger,
    InvalidAttemptTransition,
)
from apps.agent_api.tools.resolve_intent import (
    SOLANA_DEVNET_USDC_MINT,
    resolve_payment_intent,
)
from packages.schemas import PaymentIntent, SpendingPolicy

NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)
RECIPIENT = "FvJ8k8HhXp4a3zQyFMZd4FvEqcYdYE7gSZWxrEBRfBsB"


def make_intent(order: int, amount: str = "1") -> PaymentIntent:
    reference = str(Pubkey.new_unique())
    return resolve_payment_intent(
        f"solana:{RECIPIENT}?amount={amount}&spl-token={SOLANA_DEVNET_USDC_MINT}"
        f"&reference={reference}&message=Order%20{order}"
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
        "max_daily_atomic": 2_000_000,
        "max_transactions_per_day": 2,
        "max_network_fee_lamports": 100_000,
        "max_slippage_bps": 50,
        "expires_at": NOW + timedelta(days=1),
    }
    data.update(overrides)
    return SpendingPolicy.model_validate(data)


def reserve(
    ledger: InMemoryPaymentLedger,
    intent: PaymentIntent,
    *,
    session_id: str,
    policy: SpendingPolicy | None = None,
):
    return ledger.reserve(
        intent,
        policy or make_policy(),
        session_id=session_id,
        verified_merchant_id="demo-merchant",
        network_fee_lamports=5_000,
        slippage_bps=0,
        now=NOW,
    )


def test_same_intent_is_reserved_once_even_across_sessions() -> None:
    ledger = InMemoryPaymentLedger()
    intent = make_intent(1)

    first = reserve(ledger, intent, session_id="session-a")
    second = reserve(ledger, intent, session_id="session-b")

    assert first.created
    assert not second.created
    assert second.attempt.idempotency_key == first.attempt.idempotency_key
    assert len(ledger) == 1


def test_concurrent_duplicate_requests_create_one_attempt() -> None:
    ledger = InMemoryPaymentLedger()
    intent = make_intent(1)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda _: reserve(ledger, intent, session_id="same-session"),
                range(20),
            )
        )

    assert sum(result.created for result in results) == 1
    assert len(ledger) == 1


def test_concurrent_distinct_requests_cannot_overbook_daily_budget() -> None:
    ledger = InMemoryPaymentLedger()
    intents = [make_intent(order) for order in range(20)]
    policy = make_policy(max_daily_atomic=1_000_000, max_transactions_per_day=20)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(
                reserve,
                ledger,
                intent,
                session_id=f"session-{index}",
                policy=policy,
            )
            for index, intent in enumerate(intents)
        ]
        results = [future.result() for future in futures]

    assert sum(result.attempt.status is AttemptStatus.RESERVED for result in results) == 1
    assert sum(result.attempt.status is AttemptStatus.REJECTED for result in results) == 19


def test_daily_budget_is_reserved_atomically() -> None:
    ledger = InMemoryPaymentLedger()

    first = reserve(
        ledger,
        make_intent(1, "1.5"),
        session_id="session-a",
        policy=make_policy(max_per_transaction_atomic=2_000_000),
    )
    second = reserve(ledger, make_intent(2, "1"), session_id="session-b")

    assert first.attempt.status is AttemptStatus.RESERVED
    assert second.attempt.status is AttemptStatus.REJECTED
    assert "daily_budget_exceeded" in second.attempt.policy_rejection_codes


def test_failed_attempt_releases_reserved_budget_but_remains_auditable() -> None:
    ledger = InMemoryPaymentLedger()
    first = reserve(ledger, make_intent(1), session_id="session-a")
    ledger.mark_failed(first.attempt.idempotency_key, failure_code="simulation_failed", now=NOW)

    second = reserve(
        ledger,
        make_intent(2, "2"),
        session_id="session-b",
        policy=make_policy(max_per_transaction_atomic=2_000_000),
    )

    assert second.attempt.status is AttemptStatus.RESERVED
    assert ledger.get(first.attempt.idempotency_key).status is AttemptStatus.FAILED  # type: ignore[union-attr]


def test_state_machine_prevents_skipping_submission() -> None:
    ledger = InMemoryPaymentLedger()
    result = reserve(ledger, make_intent(1), session_id="session-a")

    with pytest.raises(InvalidAttemptTransition):
        ledger.mark_confirmed(result.attempt.idempotency_key, now=NOW)

    submitted = ledger.mark_submitted(
        result.attempt.idempotency_key,
        transaction_signature="demo-signature",
        now=NOW,
    )
    confirmed = ledger.mark_confirmed(submitted.idempotency_key, now=NOW)

    assert confirmed.status is AttemptStatus.CONFIRMED
    assert confirmed.transaction_signature == "demo-signature"
