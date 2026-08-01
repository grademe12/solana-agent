"""Read-only Google ADK tools for inspecting payment requests and policies."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from apps.agent_api.services import (
    GuardedMockCheckout,
    InMemoryPaymentLedger,
    MockSolanaGateway,
    MockWallet,
)
from apps.agent_api.services.policy import PolicyUsage, evaluate_payment_policy
from apps.agent_api.tools.resolve_intent import (
    SOLANA_DEVNET_USDC_MINT,
    resolve_payment_intent,
)
from packages.schemas import SpendingPolicy

_DEMO_PAYER = "11111111111111111111111111111111"
_mock_wallet = MockWallet(
    public_key=_DEMO_PAYER,
    token_balances={SOLANA_DEVNET_USDC_MINT: 100_000_000},
    sol_lamports=10_000_000,
)
_mock_gateway = MockSolanaGateway()
_mock_checkout = GuardedMockCheckout(
    ledger=InMemoryPaymentLedger(),
    wallet=_mock_wallet,
    gateway=_mock_gateway,
)


def inspect_payment_request(payload: str) -> dict[str, Any]:
    """Inspect untrusted QR text or a payment URI without fetching it or moving funds.

    Use this before discussing whether a payment request is executable. The result
    classifies the protocol and returns a normalized intent or a structured reason
    why the request is incomplete, invalid, or unsupported.
    """

    intent = resolve_payment_intent(payload)
    return {
        "status": "ok",
        "read_only": True,
        "intent": intent.model_dump(mode="json"),
    }


def preview_payment_policy(
    payload: str,
    policy_json: str,
    verified_merchant_id: str | None = None,
    network_fee_lamports: int = 0,
    slippage_bps: int = 0,
) -> dict[str, Any]:
    """Preview deterministic policy rules without reserving budget or authorizing payment.

    This tool is advisory only. Its merchant identity, fee, slippage, and zero-usage
    snapshot are caller-provided preview inputs. The guarded executor must reload
    trusted values and atomically re-evaluate the policy immediately before signing.
    """

    try:
        policy = SpendingPolicy.model_validate_json(policy_json)
    except ValidationError as exc:
        return {
            "status": "invalid_policy",
            "read_only": True,
            "advisory_only": True,
            "errors": exc.errors(include_url=False),
        }

    intent = resolve_payment_intent(payload)
    try:
        evaluation = evaluate_payment_policy(
            intent,
            policy,
            verified_merchant_id=verified_merchant_id,
            network_fee_lamports=network_fee_lamports,
            slippage_bps=slippage_bps,
            usage=PolicyUsage(),
            now=datetime.now(UTC),
        )
    except ValueError as exc:
        return {
            "status": "invalid_preview_input",
            "read_only": True,
            "advisory_only": True,
            "error": str(exc),
        }

    return {
        "status": "allowed" if evaluation.allowed else "rejected",
        "read_only": True,
        "advisory_only": True,
        "intent_id": intent.intent_id,
        "policy_id": policy.policy_id,
        "rejection_codes": [code.value for code in evaluation.rejection_codes],
        "assumptions": {
            "daily_spent_atomic": 0,
            "daily_reserved_atomic": 0,
            "transaction_count": 0,
            "verified_merchant_id": verified_merchant_id,
            "network_fee_lamports": network_fee_lamports,
            "slippage_bps": slippage_bps,
        },
    }


def execute_mock_guarded_checkout(
    payload: str,
    policy_json: str,
    session_id: str,
    demo_merchant_id: str | None = None,
) -> dict[str, Any]:
    """Execute a mock-only guarded checkout that cannot access a real wallet or network.

    Use this only when the user explicitly requests a local demonstration. The tool
    reparses the payload, applies policy and idempotency, debits an in-memory fake
    wallet, and returns a receipt marked mock with no Solana Explorer URL.
    """

    try:
        policy = SpendingPolicy.model_validate_json(policy_json)
    except ValidationError as exc:
        return {
            "status": "invalid_policy",
            "mode": "mock",
            "real_funds_moved": False,
            "errors": exc.errors(include_url=False),
        }

    result = _mock_checkout.run(
        payload,
        policy,
        session_id=session_id,
        verified_merchant_id=demo_merchant_id,
        now=datetime.now(UTC),
    )
    receipt = result.receipt
    return {
        "status": result.status.value,
        "mode": "mock",
        "real_funds_moved": False,
        "duplicate": result.duplicate,
        "intent_id": result.intent.intent_id,
        "intent_confidence": result.intent.confidence.value,
        "policy_rejection_codes": [
            code.value for code in result.attempt.policy_rejection_codes
        ],
        "failure_code": result.failure_code,
        "receipt": (
            {
                "mock": receipt.mock,
                "signature": receipt.signature,
                "network": receipt.network,
                "recipient": receipt.recipient,
                "mint": receipt.mint,
                "amount_atomic": str(receipt.amount_atomic),
                "decimals": receipt.decimals,
                "reference": receipt.reference,
                "fee_lamports": receipt.fee_lamports,
                "explorer_url": receipt.explorer_url,
            }
            if receipt is not None
            else None
        ),
    }
