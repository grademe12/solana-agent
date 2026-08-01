"""Policy-guarded orchestration for real Solana Devnet USDC checkout."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Protocol

from solders.signature import Signature

from apps.agent_api.services.idempotency import (
    AttemptStatus,
    InMemoryPaymentLedger,
    PaymentAttempt,
)
from apps.agent_api.services.receipts import (
    ReceiptVerificationError,
    SolanaPaymentReceipt,
    verify_confirmed_transaction,
)
from apps.agent_api.services.solana_transfer import (
    PreparedSolanaTransfer,
    prepared_transfer_matches_intent,
)
from apps.agent_api.tools.resolve_intent import resolve_payment_intent
from packages.schemas import PaymentIntent, SpendingPolicy


class DevnetTransferGateway(Protocol):
    async def quote_fee(self, intent: PaymentIntent) -> int: ...

    async def prepare_and_simulate(self, intent: PaymentIntent) -> PreparedSolanaTransfer: ...

    async def submit_prepared(
        self,
        prepared: PreparedSolanaTransfer,
        intent: PaymentIntent,
    ) -> Signature: ...

    async def confirm_and_fetch(
        self,
        signature: Signature,
        *,
        last_valid_block_height: int,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class DevnetCheckoutResult:
    status: AttemptStatus
    intent: PaymentIntent
    attempt: PaymentAttempt
    receipt: SolanaPaymentReceipt | None
    duplicate: bool
    failure_code: str | None


class GuardedDevnetCheckout:
    """Reserve policy budget, submit once, and verify the confirmed wire transaction."""

    def __init__(
        self,
        *,
        ledger: InMemoryPaymentLedger,
        gateway: DevnetTransferGateway,
    ) -> None:
        self._ledger = ledger
        self._gateway = gateway
        self._receipts: dict[str, SolanaPaymentReceipt] = {}
        self._receipt_lock = RLock()

    async def run(
        self,
        payload: str,
        policy: SpendingPolicy,
        *,
        session_id: str,
        verified_merchant_id: str | None,
        now: datetime,
    ) -> DevnetCheckoutResult:
        intent = resolve_payment_intent(payload)
        fee_lamports = await self._quote_if_executable(intent)
        reservation = self._ledger.reserve(
            intent,
            policy,
            session_id=session_id,
            verified_merchant_id=verified_merchant_id,
            network_fee_lamports=fee_lamports,
            slippage_bps=0,
            now=now,
        )
        attempt = reservation.attempt
        if not reservation.created:
            with self._receipt_lock:
                receipt = self._receipts.get(attempt.idempotency_key)
            return DevnetCheckoutResult(
                status=attempt.status,
                intent=intent,
                attempt=attempt,
                receipt=receipt,
                duplicate=True,
                failure_code=attempt.failure_code,
            )
        if attempt.status is AttemptStatus.REJECTED:
            return self._result(intent, attempt)

        try:
            prepared = await self._gateway.prepare_and_simulate(intent)
        except (RuntimeError, ValueError):
            return self._fail_before_submission(attempt, intent, "transaction_prepare_failed", now)
        if not prepared_transfer_matches_intent(prepared, intent):
            return self._fail_before_submission(attempt, intent, "transaction_mismatch", now)
        if (
            prepared.estimated_fee_lamports is None
            or prepared.estimated_fee_lamports > fee_lamports
        ):
            return self._fail_before_submission(attempt, intent, "fee_quote_changed", now)
        if not prepared.simulation_succeeded:
            return self._fail_before_submission(attempt, intent, "simulation_failed", now)

        # Once this call starts, an RPC transport error can be ambiguous. Do not release
        # the reservation or retry automatically unless a signature is returned.
        signature = await self._gateway.submit_prepared(prepared, intent)
        submitted = self._ledger.mark_submitted(
            attempt.idempotency_key,
            transaction_signature=str(signature),
            now=now,
        )
        try:
            response_json = await self._gateway.confirm_and_fetch(
                signature,
                last_valid_block_height=prepared.last_valid_block_height,
            )
        except RuntimeError:
            return self._result(intent, submitted, failure_code="confirmation_pending")

        try:
            receipt = verify_confirmed_transaction(
                response_json,
                intent,
                expected_payer=prepared.plan.payer,
                expected_signature=str(signature),
                confirmed_at=now,
            )
        except ReceiptVerificationError:
            return self._result(intent, submitted, failure_code="receipt_verification_failed")

        confirmed = self._ledger.mark_confirmed(attempt.idempotency_key, now=now)
        with self._receipt_lock:
            self._receipts[attempt.idempotency_key] = receipt
        return self._result(intent, confirmed, receipt=receipt)

    async def _quote_if_executable(self, intent: PaymentIntent) -> int:
        if not intent.is_executable:
            return 0
        return await self._gateway.quote_fee(intent)

    def _fail_before_submission(
        self,
        attempt: PaymentAttempt,
        intent: PaymentIntent,
        failure_code: str,
        now: datetime,
    ) -> DevnetCheckoutResult:
        failed = self._ledger.mark_failed(
            attempt.idempotency_key,
            failure_code=failure_code,
            now=now,
        )
        return self._result(intent, failed, failure_code=failure_code)

    @staticmethod
    def _result(
        intent: PaymentIntent,
        attempt: PaymentAttempt,
        *,
        receipt: SolanaPaymentReceipt | None = None,
        failure_code: str | None = None,
    ) -> DevnetCheckoutResult:
        return DevnetCheckoutResult(
            status=attempt.status,
            intent=intent,
            attempt=attempt,
            receipt=receipt,
            duplicate=False,
            failure_code=failure_code,
        )
