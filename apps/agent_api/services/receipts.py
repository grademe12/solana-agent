"""Verify confirmed Solana payments against the authoritative payment intent."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from apps.agent_api.services.solana_transfer import build_usdc_transfer_plan
from packages.schemas import PaymentIntent


class ReceiptVerificationError(RuntimeError):
    """Raised when a confirmed transaction does not prove the requested payment."""


@dataclass(frozen=True, slots=True)
class SolanaPaymentReceipt:
    network: str
    signature: str
    payer: str
    recipient: str
    mint: str
    amount_atomic: int
    decimals: int
    reference: str
    confirmed_at: datetime
    explorer_url: str


def _require_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReceiptVerificationError(f"confirmed transaction is missing {field}")
    return cast(dict[str, Any], value)


def _decode_transaction(result: dict[str, Any]) -> VersionedTransaction:
    encoded_transaction = result.get("transaction")
    if (
        not isinstance(encoded_transaction, list)
        or len(encoded_transaction) != 2
        or not isinstance(encoded_transaction[0], str)
        or encoded_transaction[1] != "base64"
    ):
        raise ReceiptVerificationError("confirmed transaction is not base64 encoded")
    try:
        raw_transaction = base64.b64decode(encoded_transaction[0], validate=True)
        return VersionedTransaction.from_bytes(raw_transaction)
    except (ValueError, TypeError) as exc:
        raise ReceiptVerificationError("confirmed transaction bytes are invalid") from exc


def verify_confirmed_transaction(
    response_json: str,
    intent: PaymentIntent,
    *,
    expected_payer: Pubkey,
    expected_signature: str,
    confirmed_at: datetime,
) -> SolanaPaymentReceipt:
    """Rebuild the expected message and compare it with the confirmed wire transaction."""

    if confirmed_at.utcoffset() is None:
        raise ValueError("confirmed_at must include a timezone")
    if not expected_signature:
        raise ValueError("expected_signature is required")
    try:
        payload = cast(object, json.loads(response_json))
    except json.JSONDecodeError as exc:
        raise ReceiptVerificationError("confirmed transaction response is invalid JSON") from exc

    root = _require_mapping(payload, "RPC response")
    result = _require_mapping(root.get("result"), "result")
    meta = _require_mapping(result.get("meta"), "meta")
    if meta.get("err") is not None:
        raise ReceiptVerificationError("confirmed transaction failed on chain")

    transaction = _decode_transaction(result)
    if not transaction.signatures or str(transaction.signatures[0]) != expected_signature:
        raise ReceiptVerificationError("confirmed transaction signature does not match submission")
    if transaction.verify_with_results() != [True]:
        raise ReceiptVerificationError("confirmed transaction signature is invalid")
    if not isinstance(transaction.message, MessageV0):
        raise ReceiptVerificationError("confirmed transaction is not a versioned P0 transaction")
    if transaction.message.address_table_lookups:
        raise ReceiptVerificationError("P0 transactions must not use address lookup tables")

    plan = build_usdc_transfer_plan(intent, payer=expected_payer)
    expected_message = MessageV0.try_compile(
        expected_payer,
        list(plan.instructions),
        [],
        transaction.message.recent_blockhash,
    )
    if transaction.message != expected_message:
        raise ReceiptVerificationError("confirmed transaction does not match payment intent")
    if intent.asset is None or intent.amount is None:
        raise ReceiptVerificationError("payment intent is incomplete")

    return SolanaPaymentReceipt(
        network=intent.network,
        signature=expected_signature,
        payer=str(expected_payer),
        recipient=str(plan.recipient),
        mint=str(plan.mint),
        amount_atomic=plan.amount_atomic,
        decimals=plan.decimals,
        reference=str(plan.reference),
        confirmed_at=confirmed_at,
        explorer_url=(
            f"https://explorer.solana.com/tx/{expected_signature}?cluster=devnet"
        ),
    )
