"""Deterministic mock Solana adapter for end-to-end local checkout tests."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from packages.schemas import PaymentIntent


class InsufficientMockBalance(RuntimeError):
    """Raised before mock submission when token or fee balance is insufficient."""


@dataclass(frozen=True, slots=True)
class MockWalletSnapshot:
    public_key: str
    token_balances: dict[str, int]
    sol_lamports: int


class MockWallet:
    """Thread-safe fake wallet that never contains or handles private keys."""

    def __init__(
        self,
        *,
        public_key: str,
        token_balances: dict[str, int],
        sol_lamports: int,
    ) -> None:
        if sol_lamports < 0 or any(amount < 0 for amount in token_balances.values()):
            raise ValueError("mock wallet balances cannot be negative")
        self._public_key = public_key
        self._token_balances = dict(token_balances)
        self._sol_lamports = sol_lamports
        self._lock = RLock()

    @property
    def public_key(self) -> str:
        return self._public_key

    def snapshot(self) -> MockWalletSnapshot:
        with self._lock:
            return MockWalletSnapshot(
                public_key=self._public_key,
                token_balances=dict(self._token_balances),
                sol_lamports=self._sol_lamports,
            )

    def can_debit(self, *, mint: str, amount_atomic: int, fee_lamports: int) -> bool:
        with self._lock:
            return (
                amount_atomic >= 0
                and fee_lamports >= 0
                and self._token_balances.get(mint, 0) >= amount_atomic
                and self._sol_lamports >= fee_lamports
            )

    def debit(self, *, mint: str, amount_atomic: int, fee_lamports: int) -> None:
        with self._lock:
            if not self.can_debit(
                mint=mint,
                amount_atomic=amount_atomic,
                fee_lamports=fee_lamports,
            ):
                raise InsufficientMockBalance("mock wallet has insufficient token or SOL balance")
            self._token_balances[mint] -= amount_atomic
            self._sol_lamports -= fee_lamports


@dataclass(frozen=True, slots=True)
class MockTransferPlan:
    network: str
    payer: str
    recipient: str
    mint: str
    amount_atomic: int
    decimals: int
    reference: str
    fee_lamports: int


@dataclass(frozen=True, slots=True)
class MockPaymentReceipt:
    mock: bool
    network: str
    signature: str
    payer: str
    recipient: str
    mint: str
    amount_atomic: int
    decimals: int
    reference: str
    fee_lamports: int
    confirmed_at: datetime
    explorer_url: None = None


class MockSolanaGateway:
    """Fake network adapter with the same guarded stages as a Solana submission."""

    def __init__(self, *, fee_lamports: int = 5_000) -> None:
        if fee_lamports < 0:
            raise ValueError("mock network fee cannot be negative")
        self.fee_lamports = fee_lamports
        self.submit_count = 0
        self._lock = RLock()

    def build_transfer(self, intent: PaymentIntent, *, payer: str) -> MockTransferPlan:
        if not intent.is_executable or intent.amount is None or intent.asset is None:
            raise ValueError("cannot build a transfer from a non-executable intent")
        if intent.recipient is None or intent.asset.mint is None or intent.reference is None:
            raise ValueError("executable intent is missing transfer fields")
        return MockTransferPlan(
            network=intent.network,
            payer=payer,
            recipient=intent.recipient,
            mint=intent.asset.mint,
            amount_atomic=intent.amount.atomic,
            decimals=intent.amount.decimals,
            reference=intent.reference,
            fee_lamports=self.fee_lamports,
        )

    def simulate(self, plan: MockTransferPlan, *, wallet: MockWallet) -> bool:
        return wallet.can_debit(
            mint=plan.mint,
            amount_atomic=plan.amount_atomic,
            fee_lamports=plan.fee_lamports,
        )

    def submit(
        self,
        plan: MockTransferPlan,
        *,
        wallet: MockWallet,
        now: datetime,
    ) -> MockPaymentReceipt:
        if now.utcoffset() is None:
            raise ValueError("now must include a timezone")
        with self._lock:
            wallet.debit(
                mint=plan.mint,
                amount_atomic=plan.amount_atomic,
                fee_lamports=plan.fee_lamports,
            )
            self.submit_count += 1
            signature_material = "|".join(
                (
                    "mock-solana",
                    str(self.submit_count),
                    plan.network,
                    plan.payer,
                    plan.recipient,
                    plan.mint,
                    str(plan.amount_atomic),
                    plan.reference,
                )
            )
            signature = "mock:" + hashlib.sha256(
                signature_material.encode("utf-8")
            ).hexdigest()
            return MockPaymentReceipt(
                mock=True,
                network=plan.network,
                signature=signature,
                payer=plan.payer,
                recipient=plan.recipient,
                mint=plan.mint,
                amount_atomic=plan.amount_atomic,
                decimals=plan.decimals,
                reference=plan.reference,
                fee_lamports=plan.fee_lamports,
                confirmed_at=now,
            )


def transfer_plan_matches_intent(plan: MockTransferPlan, intent: PaymentIntent) -> bool:
    """Reject any transaction plan that differs from the normalized request."""

    return bool(
        intent.is_executable
        and intent.amount is not None
        and intent.asset is not None
        and plan.network == intent.network
        and plan.recipient == intent.recipient
        and plan.mint == intent.asset.mint
        and plan.amount_atomic == intent.amount.atomic
        and plan.decimals == intent.amount.decimals
        and plan.reference == intent.reference
    )


def mock_receipt_matches_intent(receipt: MockPaymentReceipt, intent: PaymentIntent) -> bool:
    """Verify the mock receipt using the fields required for on-chain verification."""

    return bool(
        receipt.mock
        and intent.is_executable
        and intent.amount is not None
        and intent.asset is not None
        and receipt.network == intent.network
        and receipt.recipient == intent.recipient
        and receipt.mint == intent.asset.mint
        and receipt.amount_atomic == intent.amount.atomic
        and receipt.decimals == intent.amount.decimals
        and receipt.reference == intent.reference
        and receipt.signature.startswith("mock:")
        and receipt.explorer_url is None
    )

