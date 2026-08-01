"""Atomic in-memory budget reservations and payment idempotency for local P0."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum
from threading import RLock

from apps.agent_api.services.policy import (
    PolicyEvaluation,
    PolicyRejectionCode,
    PolicyUsage,
    evaluate_payment_policy,
)
from packages.schemas import PaymentIntent, SpendingPolicy


class AttemptStatus(StrEnum):
    REJECTED = "rejected"
    RESERVED = "reserved"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class InvalidAttemptTransition(RuntimeError):
    """Raised when payment execution tries to skip the guarded state machine."""


@dataclass(frozen=True, slots=True)
class PaymentAttempt:
    idempotency_key: str
    intent_id: str
    policy_id: str
    user_id: str
    session_id: str
    budget_date: date
    amount_atomic: int
    status: AttemptStatus
    policy_rejection_codes: tuple[PolicyRejectionCode, ...]
    transaction_signature: str | None
    failure_code: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ReservationResult:
    attempt: PaymentAttempt
    evaluation: PolicyEvaluation
    created: bool


def make_idempotency_key(*, intent_id: str, user_id: str, session_id: str) -> str:
    """Hash length-delimited identifiers so concatenation cannot create collisions."""

    digest = hashlib.sha256()
    for value in (intent_id, user_id, session_id):
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return "sha256:" + digest.hexdigest()


class InMemoryPaymentLedger:
    """Thread-safe local adapter; Cloud deployment will replace it with Firestore."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._attempts: dict[str, PaymentAttempt] = {}
        self._intent_index: dict[tuple[str, str], str] = {}

    def _budget_date(self, policy: SpendingPolicy, now: datetime) -> date:
        return now.astimezone(policy.expires_at.tzinfo).date()

    def _usage(self, policy: SpendingPolicy, budget_date: date) -> PolicyUsage:
        matching = (
            attempt
            for attempt in self._attempts.values()
            if attempt.user_id == policy.user_id
            and attempt.policy_id == policy.policy_id
            and attempt.budget_date == budget_date
        )
        spent = 0
        reserved = 0
        count = 0
        for attempt in matching:
            if attempt.status is AttemptStatus.CONFIRMED:
                spent += attempt.amount_atomic
                count += 1
            elif attempt.status in {AttemptStatus.RESERVED, AttemptStatus.SUBMITTED}:
                reserved += attempt.amount_atomic
                count += 1
        return PolicyUsage(
            daily_spent_atomic=spent,
            daily_reserved_atomic=reserved,
            transaction_count=count,
        )

    def reserve(
        self,
        intent: PaymentIntent,
        policy: SpendingPolicy,
        *,
        session_id: str,
        verified_merchant_id: str | None,
        network_fee_lamports: int,
        slippage_bps: int,
        now: datetime,
    ) -> ReservationResult:
        """Evaluate policy and reserve budget atomically, or return the prior attempt."""

        if not session_id:
            raise ValueError("session_id is required")
        if now.utcoffset() is None:
            raise ValueError("now must include a timezone")
        key = make_idempotency_key(
            intent_id=intent.intent_id,
            user_id=policy.user_id,
            session_id=session_id,
        )

        with self._lock:
            existing_key = self._intent_index.get((policy.user_id, intent.intent_id))
            existing = self._attempts.get(existing_key or key)
            budget_date = self._budget_date(policy, now)
            usage = self._usage(policy, budget_date)
            if existing is not None:
                evaluation = PolicyEvaluation(
                    allowed=not existing.policy_rejection_codes,
                    rejection_codes=existing.policy_rejection_codes,
                    evaluated_at=now,
                    usage=usage,
                )
                return ReservationResult(attempt=existing, evaluation=evaluation, created=False)

            evaluation = evaluate_payment_policy(
                intent,
                policy,
                verified_merchant_id=verified_merchant_id,
                network_fee_lamports=network_fee_lamports,
                slippage_bps=slippage_bps,
                usage=usage,
                now=now,
            )
            amount_atomic = intent.amount.atomic if intent.amount is not None else 0
            status = AttemptStatus.RESERVED if evaluation.allowed else AttemptStatus.REJECTED
            attempt = PaymentAttempt(
                idempotency_key=key,
                intent_id=intent.intent_id,
                policy_id=policy.policy_id,
                user_id=policy.user_id,
                session_id=session_id,
                budget_date=budget_date,
                amount_atomic=amount_atomic,
                status=status,
                policy_rejection_codes=evaluation.rejection_codes,
                transaction_signature=None,
                failure_code=None,
                created_at=now,
                updated_at=now,
            )
            self._attempts[key] = attempt
            self._intent_index[(policy.user_id, intent.intent_id)] = key
            return ReservationResult(attempt=attempt, evaluation=evaluation, created=True)

    def mark_submitted(
        self, idempotency_key: str, *, transaction_signature: str, now: datetime
    ) -> PaymentAttempt:
        if not transaction_signature:
            raise ValueError("transaction_signature is required")
        return self._transition(
            idempotency_key,
            expected=AttemptStatus.RESERVED,
            target=AttemptStatus.SUBMITTED,
            now=now,
            transaction_signature=transaction_signature,
        )

    def mark_confirmed(self, idempotency_key: str, *, now: datetime) -> PaymentAttempt:
        return self._transition(
            idempotency_key,
            expected=AttemptStatus.SUBMITTED,
            target=AttemptStatus.CONFIRMED,
            now=now,
        )

    def mark_failed(
        self, idempotency_key: str, *, failure_code: str, now: datetime
    ) -> PaymentAttempt:
        if not failure_code:
            raise ValueError("failure_code is required")
        if now.utcoffset() is None:
            raise ValueError("now must include a timezone")
        with self._lock:
            attempt = self._require_attempt(idempotency_key)
            if attempt.status not in {AttemptStatus.RESERVED, AttemptStatus.SUBMITTED}:
                raise InvalidAttemptTransition(
                    f"cannot transition {attempt.status} to {AttemptStatus.FAILED}"
                )
            updated = replace(
                attempt,
                status=AttemptStatus.FAILED,
                failure_code=failure_code,
                updated_at=now,
            )
            self._attempts[idempotency_key] = updated
            return updated

    def get(self, idempotency_key: str) -> PaymentAttempt | None:
        with self._lock:
            return self._attempts.get(idempotency_key)

    def __len__(self) -> int:
        with self._lock:
            return len(self._attempts)

    def _require_attempt(self, idempotency_key: str) -> PaymentAttempt:
        try:
            return self._attempts[idempotency_key]
        except KeyError as exc:
            raise KeyError("payment attempt does not exist") from exc

    def _transition(
        self,
        idempotency_key: str,
        *,
        expected: AttemptStatus,
        target: AttemptStatus,
        now: datetime,
        transaction_signature: str | None = None,
    ) -> PaymentAttempt:
        if now.utcoffset() is None:
            raise ValueError("now must include a timezone")
        with self._lock:
            attempt = self._require_attempt(idempotency_key)
            if attempt.status is not expected:
                raise InvalidAttemptTransition(
                    f"cannot transition {attempt.status} to {target}"
                )
            updated = replace(
                attempt,
                status=target,
                transaction_signature=transaction_signature or attempt.transaction_signature,
                updated_at=now,
            )
            self._attempts[idempotency_key] = updated
            return updated
