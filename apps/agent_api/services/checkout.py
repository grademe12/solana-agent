"""Guarded checkout orchestration shared by mock and future Solana adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from apps.agent_api.services.idempotency import (
    AttemptStatus,
    InMemoryPaymentLedger,
    PaymentAttempt,
)
from apps.agent_api.services.mock_solana import (
    MockPaymentReceipt,
    MockSolanaGateway,
    MockWallet,
    mock_receipt_matches_intent,
    transfer_plan_matches_intent,
)
from apps.agent_api.tools.resolve_intent import resolve_payment_intent
from packages.schemas import PaymentIntent, SpendingPolicy


@dataclass(frozen=True, slots=True)
class CheckoutResult:
    status: AttemptStatus
    intent: PaymentIntent
    attempt: PaymentAttempt
    receipt: MockPaymentReceipt | None
    duplicate: bool
    failure_code: str | None


class GuardedMockCheckout:
    """Run a payment through all safety gates without touching a real network."""

    def __init__(
        self,
        *,
        ledger: InMemoryPaymentLedger,
        wallet: MockWallet,
        gateway: MockSolanaGateway,
    ) -> None:
        self._ledger = ledger
        self._wallet = wallet
        self._gateway = gateway
        self._receipts: dict[str, MockPaymentReceipt] = {}
        self._receipt_lock = RLock()

    def run(
        self,
        payload: str,
        policy: SpendingPolicy,
        *,
        session_id: str,
        verified_merchant_id: str | None,
        now: datetime,
    ) -> CheckoutResult:
        """Reparse, authorize, simulate, submit, and verify one mock payment."""

        intent = resolve_payment_intent(payload)
        reservation = self._ledger.reserve(
            intent,
            policy,
            session_id=session_id,
            verified_merchant_id=verified_merchant_id,
            network_fee_lamports=self._gateway.fee_lamports,
            slippage_bps=0,
            now=now,
        )
        attempt = reservation.attempt
        if not reservation.created:
            with self._receipt_lock:
                receipt = self._receipts.get(attempt.idempotency_key)
            return CheckoutResult(
                status=attempt.status,
                intent=intent,
                attempt=attempt,
                receipt=receipt,
                duplicate=True,
                failure_code=attempt.failure_code,
            )
        if attempt.status is AttemptStatus.REJECTED:
            return CheckoutResult(
                status=attempt.status,
                intent=intent,
                attempt=attempt,
                receipt=None,
                duplicate=False,
                failure_code=None,
            )

        try:
            plan = self._gateway.build_transfer(intent, payer=self._wallet.public_key)
        except ValueError:
            return self._fail(attempt, intent, "transaction_build_failed", now)

        if not transfer_plan_matches_intent(plan, intent):
            return self._fail(attempt, intent, "transaction_plan_mismatch", now)
        if not self._gateway.simulate(plan, wallet=self._wallet):
            return self._fail(attempt, intent, "insufficient_balance", now)

        try:
            receipt = self._gateway.submit(plan, wallet=self._wallet, now=now)
        except RuntimeError:
            return self._fail(attempt, intent, "mock_submission_failed", now)

        submitted = self._ledger.mark_submitted(
            attempt.idempotency_key,
            transaction_signature=receipt.signature,
            now=now,
        )
        if not mock_receipt_matches_intent(receipt, intent):
            return CheckoutResult(
                status=submitted.status,
                intent=intent,
                attempt=submitted,
                receipt=receipt,
                duplicate=False,
                failure_code="receipt_verification_failed",
            )

        confirmed = self._ledger.mark_confirmed(attempt.idempotency_key, now=now)
        with self._receipt_lock:
            self._receipts[attempt.idempotency_key] = receipt
        return CheckoutResult(
            status=confirmed.status,
            intent=intent,
            attempt=confirmed,
            receipt=receipt,
            duplicate=False,
            failure_code=None,
        )

    def _fail(
        self,
        attempt: PaymentAttempt,
        intent: PaymentIntent,
        failure_code: str,
        now: datetime,
    ) -> CheckoutResult:
        failed = self._ledger.mark_failed(
            attempt.idempotency_key,
            failure_code=failure_code,
            now=now,
        )
        return CheckoutResult(
            status=failed.status,
            intent=intent,
            attempt=failed,
            receipt=None,
            duplicate=False,
            failure_code=failure_code,
        )

