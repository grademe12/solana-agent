from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from packages.schemas import (
    IntentConfidence,
    PaymentAsset,
    PaymentIntent,
    PaymentProtocol,
    TokenAmount,
)

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def make_authoritative_intent() -> PaymentIntent:
    return PaymentIntent(
        intent_id=HASH_A,
        protocol=PaymentProtocol.SOLANA_PAY,
        network="solana:devnet",
        recipient="DemoRecipient",
        amount=TokenAmount(atomic=100_000, decimals=6),
        asset=PaymentAsset(symbol="USDC", mint="DemoUsdcMint", decimals=6),
        reference="OrderReference",
        merchant_id="demo-merchant",
        label="Demo Merchant",
        message="Order #123",
        expires_at=datetime(2026, 8, 2, tzinfo=UTC),
        source_payload_hash=HASH_B,
        confidence=IntentConfidence.AUTHORITATIVE,
    )


def test_authoritative_intent_is_executable() -> None:
    intent = make_authoritative_intent()

    assert intent.is_executable is True
    assert intent.amount_display == "0.1"
    assert intent.model_dump(mode="json")["amount"]["atomic"] == "100000"


def test_authoritative_intent_requires_reference() -> None:
    data = make_authoritative_intent().model_dump()
    data["reference"] = None

    with pytest.raises(ValidationError, match="reference"):
        PaymentIntent.model_validate(data)


def test_amount_and_asset_decimals_must_match() -> None:
    data = make_authoritative_intent().model_dump()
    data["amount"] = TokenAmount(atomic=100_000, decimals=5)

    with pytest.raises(ValidationError, match="decimals must match"):
        PaymentIntent.model_validate(data)


def test_unsupported_intent_is_structured_and_not_executable() -> None:
    intent = PaymentIntent(
        intent_id=HASH_A,
        protocol=PaymentProtocol.BASE_PAY,
        network="base:mainnet",
        source_payload_hash=HASH_B,
        confidence=IntentConfidence.UNSUPPORTED,
        rejection_code="unsupported_network",
        rejection_reason="Only Solana payments are supported in P0.",
    )

    assert intent.is_executable is False
    assert intent.rejection_code == "unsupported_network"


def test_naive_expiry_is_rejected() -> None:
    data = make_authoritative_intent().model_dump()
    data["expires_at"] = datetime(2026, 8, 2)

    with pytest.raises(ValidationError, match="timezone"):
        PaymentIntent.model_validate(data)
