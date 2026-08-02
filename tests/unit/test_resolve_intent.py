from apps.agent_api.tools.resolve_intent import (
    SOLANA_DEVNET_USDC_MINT,
    SOLANA_MAINNET_USDC_MINT,
    resolve_payment_intent,
)
from packages.schemas import IntentConfidence, PaymentProtocol

RECIPIENT = "FvJ8k8HhXp4a3zQyFMZd4FvEqcYdYE7gSZWxrEBRfBsB"
REFERENCE = "11111111111111111111111111111111"
BASE_PAY_PAYLOAD = (
    "https://base.app/base-pay?"
    "paymentSessionId=paymentSession_d094d3bb-9490-42c4-87e0-6537866fba4b"
    "&baseURL=https%3A%2F%2Fapi.cdp.coinbase.com%2Fplatform"
    "&amount=10.00&asset=usdc"
)


def test_resolves_authoritative_devnet_usdc_transfer() -> None:
    payload = (
        f"solana:{RECIPIENT}?amount=1.25&spl-token={SOLANA_DEVNET_USDC_MINT}"
        f"&reference={REFERENCE}&label=Demo%20Merchant&message=Order%20123"
    )

    intent = resolve_payment_intent(payload)

    assert intent.confidence is IntentConfidence.AUTHORITATIVE
    assert intent.protocol is PaymentProtocol.SOLANA_PAY
    assert intent.network == "solana:devnet"
    assert intent.amount is not None
    assert intent.amount.atomic == 1_250_000
    assert intent.asset is not None
    assert intent.asset.mint == SOLANA_DEVNET_USDC_MINT
    assert intent.reference == REFERENCE
    assert intent.label == "Demo Merchant"
    assert intent.message == "Order 123"


def test_rejects_base_eip681_request_before_execution() -> None:
    payload = "ethereum:0x1111111111111111111111111111111111111111@8453/transfer?value=1000000"

    intent = resolve_payment_intent(payload)

    assert intent.confidence is IntentConfidence.UNSUPPORTED
    assert intent.protocol is PaymentProtocol.BASE_PAY
    assert intent.network == "eip155:8453"
    assert intent.rejection_code == "unsupported_network"
    assert not intent.is_executable


def test_classifies_base_app_payment_details_before_safe_rejection() -> None:
    intent = resolve_payment_intent(BASE_PAY_PAYLOAD)

    assert intent.confidence is IntentConfidence.UNSUPPORTED
    assert intent.protocol is PaymentProtocol.BASE_PAY
    assert intent.network == "eip155:8453"
    assert intent.rejection_code == "unsupported_network"
    assert intent.amount is not None
    assert intent.amount.atomic == 10_000_000
    assert intent.asset is not None
    assert intent.asset.symbol == "USDC"
    assert intent.asset.mint is None
    assert not intent.is_executable


def test_raw_solana_address_is_incomplete() -> None:
    intent = resolve_payment_intent(RECIPIENT)

    assert intent.confidence is IntentConfidence.INCOMPLETE
    assert intent.protocol is PaymentProtocol.RAW_ADDRESS
    assert intent.rejection_code == "missing_payment_terms"


def test_missing_reference_is_incomplete() -> None:
    payload = f"solana:{RECIPIENT}?amount=1&spl-token={SOLANA_DEVNET_USDC_MINT}"

    intent = resolve_payment_intent(payload)

    assert intent.confidence is IntentConfidence.INCOMPLETE
    assert intent.rejection_code == "missing_reference"


def test_mainnet_usdc_is_rejected_in_devnet_only_p0() -> None:
    payload = (
        f"solana:{RECIPIENT}?amount=1&spl-token={SOLANA_MAINNET_USDC_MINT}"
        f"&reference={REFERENCE}"
    )

    intent = resolve_payment_intent(payload)

    assert intent.confidence is IntentConfidence.UNSUPPORTED
    assert intent.network == "solana:mainnet"
    assert intent.rejection_code == "unsupported_network"


def test_scientific_notation_amount_is_invalid() -> None:
    payload = (
        f"solana:{RECIPIENT}?amount=1e-3&spl-token={SOLANA_DEVNET_USDC_MINT}"
        f"&reference={REFERENCE}"
    )

    intent = resolve_payment_intent(payload)

    assert intent.confidence is IntentConfidence.INVALID
    assert intent.rejection_code == "invalid_amount"


def test_unknown_url_is_unsupported_without_network_access() -> None:
    intent = resolve_payment_intent("https://example.invalid/pay/123")

    assert intent.confidence is IntentConfidence.UNSUPPORTED
    assert intent.rejection_code == "unsupported_protocol"
