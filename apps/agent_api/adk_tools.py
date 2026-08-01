"""Read-only Google ADK tools for inspecting payment requests and policies."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from apps.agent_api.services.policy import PolicyUsage, evaluate_payment_policy
from apps.agent_api.tools.resolve_intent import resolve_payment_intent
from packages.schemas import SpendingPolicy


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

