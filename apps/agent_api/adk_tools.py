"""Google ADK tools with a guarded boundary around payment execution."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from apps.agent_api.services import (
    DevnetUsdcTransferService,
    GuardedDevnetCheckout,
    GuardedMockCheckout,
    InMemoryPaymentLedger,
    MockSolanaGateway,
    MockWallet,
)
from apps.agent_api.services.authorizations import InMemoryAuthorizationStore
from apps.agent_api.services.devnet_rpc import DevnetRpcService
from apps.agent_api.services.keypairs import load_keypair_file
from apps.agent_api.services.policy import PolicyUsage, evaluate_payment_policy
from apps.agent_api.settings import SolanaSettings
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
_authorization_store = InMemoryAuthorizationStore()
_devnet_checkout: GuardedDevnetCheckout | None = None


def authorization_store() -> InMemoryAuthorizationStore:
    """Return the process-local authorization store used by the API and ADK tool."""

    return _authorization_store


def _get_devnet_checkout(settings: SolanaSettings) -> GuardedDevnetCheckout:
    global _devnet_checkout
    if _devnet_checkout is None:
        _devnet_checkout = GuardedDevnetCheckout(
            ledger=InMemoryPaymentLedger(),
            gateway=DevnetUsdcTransferService(settings),
        )
    return _devnet_checkout


async def get_agent_wallet_balances() -> dict[str, Any]:
    """Read the configured agent wallet's public SOL and USDC balances.

    This tool never accepts a wallet path, RPC endpoint, network, mint, or private
    key from the model and never signs or submits a transaction.
    """

    settings = SolanaSettings()
    if settings.payment_execution_mode == "mock":
        mock_snapshot = _mock_wallet.snapshot()
        return {
            "status": "ok",
            "mode": "mock",
            "read_only": True,
            "wallet": mock_snapshot.public_key,
            "sol_lamports": mock_snapshot.sol_lamports,
            "usdc_atomic": str(
                mock_snapshot.token_balances.get(SOLANA_DEVNET_USDC_MINT, 0)
            ),
            "usdc_decimals": 6,
            "slot": None,
        }

    signer = load_keypair_file(settings.resolved_keypair_path())
    devnet_snapshot = await DevnetRpcService(settings).probe(signer.pubkey())
    return {
        "status": "ok",
        "mode": "devnet",
        "read_only": True,
        "wallet": str(signer.pubkey()),
        "sol_lamports": devnet_snapshot.wallet_balance_lamports,
        "usdc_atomic": str(devnet_snapshot.wallet_usdc_atomic),
        "usdc_decimals": devnet_snapshot.usdc_decimals,
        "slot": devnet_snapshot.slot,
    }


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


def inspect_authorized_payment(authorization_id: str) -> dict[str, Any]:
    """Inspect the immutable payment request bound to a server authorization.

    The model receives normalized public payment fields, but the raw payload stays in
    server memory and cannot be reconstructed or replaced at execution time.
    """

    authorization = _authorization_store.get(authorization_id)
    if authorization is None:
        return {
            "status": "authorization_not_found",
            "read_only": True,
        }

    intent = resolve_payment_intent(authorization.payment_payload)
    binding_valid = (
        intent.intent_id == authorization.intent_id
        and intent.source_payload_hash == authorization.source_payload_hash
    )
    return {
        "status": "ok" if binding_valid else "authorization_binding_mismatch",
        "read_only": True,
        "authorization_id": authorization.authorization_id,
        "binding_valid": binding_valid,
        "intent": intent.model_dump(mode="json") if binding_valid else None,
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


async def execute_authorized_checkout(
    authorization_id: str,
) -> dict[str, Any]:
    """Execute using a server-stored user policy identified by an authorization ID.

    The tool deliberately does not accept policy limits, merchant identity, wallet
    paths, network endpoints, or signing material from the model. In Devnet mode it
    can move real Devnet assets, so call it only after explicit user authorization.
    """

    authorization = _authorization_store.get(authorization_id)
    if authorization is None:
        return {"status": "authorization_not_found", "submitted": False}

    settings = SolanaSettings()
    payload = authorization.payment_payload
    intent = resolve_payment_intent(payload)
    if (
        intent.intent_id != authorization.intent_id
        or intent.source_payload_hash != authorization.source_payload_hash
    ):
        return {
            "status": "authorization_binding_mismatch",
            "submitted": False,
            "intent_id": authorization.intent_id,
        }
    if intent.recipient != settings.demo_merchant_recipient:
        return {
            "status": "unverified_merchant",
            "submitted": False,
            "intent_id": intent.intent_id,
        }

    now = datetime.now(UTC)
    if settings.payment_execution_mode == "mock":
        result = _mock_checkout.run(
            payload,
            authorization.policy,
            session_id=authorization.session_id,
            verified_merchant_id=settings.demo_merchant_id,
            now=now,
        )
        mock_receipt = result.receipt
        return {
            "status": result.status.value,
            "mode": "mock",
            "submitted": result.status.value in {"submitted", "confirmed"},
            "real_funds_moved": False,
            "duplicate": result.duplicate,
            "intent_id": result.intent.intent_id,
            "failure_code": result.failure_code,
            "policy_rejection_codes": [
                code.value for code in result.attempt.policy_rejection_codes
            ],
            "receipt": (
                {
                    "mock": True,
                    "signature": mock_receipt.signature,
                    "network": mock_receipt.network,
                    "recipient": mock_receipt.recipient,
                    "mint": mock_receipt.mint,
                    "amount_atomic": str(mock_receipt.amount_atomic),
                    "decimals": mock_receipt.decimals,
                    "reference": mock_receipt.reference,
                    "explorer_url": None,
                }
                if mock_receipt is not None
                else None
            ),
        }

    checkout = _get_devnet_checkout(settings)
    devnet_result = await checkout.run(
        payload,
        authorization.policy,
        session_id=authorization.session_id,
        verified_merchant_id=settings.demo_merchant_id,
        now=now,
    )
    devnet_receipt = devnet_result.receipt
    return {
        "status": devnet_result.status.value,
        "mode": "devnet",
        "submitted": devnet_result.status.value in {"submitted", "confirmed"},
        "real_funds_moved": devnet_result.status.value == "confirmed",
        "duplicate": devnet_result.duplicate,
        "intent_id": devnet_result.intent.intent_id,
        "failure_code": devnet_result.failure_code,
        "policy_rejection_codes": [
            code.value for code in devnet_result.attempt.policy_rejection_codes
        ],
        "receipt": (
            {
                "mock": False,
                "signature": devnet_receipt.signature,
                "network": devnet_receipt.network,
                "recipient": devnet_receipt.recipient,
                "mint": devnet_receipt.mint,
                "amount_atomic": str(devnet_receipt.amount_atomic),
                "decimals": devnet_receipt.decimals,
                "reference": devnet_receipt.reference,
                "explorer_url": devnet_receipt.explorer_url,
            }
            if devnet_receipt is not None
            else None
        ),
    }
