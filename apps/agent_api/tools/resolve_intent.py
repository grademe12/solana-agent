"""Normalize untrusted payment text into a protocol-neutral intent."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from solders.pubkey import Pubkey

from packages.schemas import (
    IntentConfidence,
    PaymentAsset,
    PaymentIntent,
    PaymentProtocol,
    TokenAmount,
)

SOLANA_DEVNET_USDC_MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
SOLANA_MAINNET_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
DECIMAL_AMOUNT_PATTERN = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
BASE_CHAIN_IDS = frozenset({"8453", "84532"})
BASE_PAYMENT_HOSTS = frozenset({"pay.coinbase.com", "commerce.coinbase.com"})
BASE_APP_PAYMENT_HOST = "base.app"
BASE_APP_PAYMENT_PATH = "/base-pay"
BASE_USDC_DECIMALS = 6


@dataclass(frozen=True, slots=True)
class KnownAsset:
    symbol: str
    mint: str
    decimals: int
    network: str
    enabled: bool


KNOWN_ASSETS = {
    SOLANA_DEVNET_USDC_MINT: KnownAsset(
        symbol="USDC",
        mint=SOLANA_DEVNET_USDC_MINT,
        decimals=6,
        network="solana:devnet",
        enabled=True,
    ),
    SOLANA_MAINNET_USDC_MINT: KnownAsset(
        symbol="USDC",
        mint=SOLANA_MAINNET_USDC_MINT,
        decimals=6,
        network="solana:mainnet",
        enabled=False,
    ),
}


def _hash_payload(payload: str) -> str:
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _valid_pubkey(value: str) -> bool:
    try:
        Pubkey.from_string(value)
    except ValueError:
        return False
    return True


def _rejected(
    payload: str,
    *,
    protocol: PaymentProtocol,
    network: str,
    confidence: IntentConfidence,
    code: str,
    reason: str,
    recipient: str | None = None,
    amount: TokenAmount | None = None,
    asset: PaymentAsset | None = None,
) -> PaymentIntent:
    payload_hash = _hash_payload(payload)
    return PaymentIntent(
        intent_id=payload_hash,
        protocol=protocol,
        network=network,
        recipient=recipient,
        amount=amount,
        asset=asset,
        source_payload_hash=payload_hash,
        confidence=confidence,
        rejection_code=code,
        rejection_reason=reason,
    )


def _single_query_value(
    query: dict[str, list[str]], key: str, *, required: bool = False
) -> str | None:
    values = query.get(key, [])
    if not values:
        if required:
            raise ValueError(f"missing_{key}")
        return None
    if len(values) != 1 or not values[0]:
        raise ValueError(f"invalid_{key}")
    return values[0]


def _resolve_solana_pay(payload: str) -> PaymentIntent:
    parsed = urlsplit(payload)
    recipient = parsed.path
    if recipient.startswith(("http://", "https://")):
        return _rejected(
            payload,
            protocol=PaymentProtocol.SOLANA_PAY,
            network="solana:unknown",
            confidence=IntentConfidence.UNSUPPORTED,
            code="unsupported_transaction_request",
            reason="P0 supports Solana Pay transfer requests only",
        )
    if not _valid_pubkey(recipient):
        return _rejected(
            payload,
            protocol=PaymentProtocol.SOLANA_PAY,
            network="solana:unknown",
            confidence=IntentConfidence.INVALID,
            code="invalid_recipient",
            reason="Solana Pay recipient is not a valid public key",
        )

    query = parse_qs(parsed.query, keep_blank_values=True)
    try:
        amount_text = _single_query_value(query, "amount")
        mint = _single_query_value(query, "spl-token")
        reference = _single_query_value(query, "reference")
        label = _single_query_value(query, "label")
        message = _single_query_value(query, "message")
    except ValueError as exc:
        return _rejected(
            payload,
            protocol=PaymentProtocol.SOLANA_PAY,
            network="solana:unknown",
            confidence=IntentConfidence.INVALID,
            code=str(exc),
            reason="Solana Pay request has a missing, empty, or duplicate field",
            recipient=recipient,
        )

    if mint is None:
        return _rejected(
            payload,
            protocol=PaymentProtocol.SOLANA_PAY,
            network="solana:unknown",
            confidence=IntentConfidence.UNSUPPORTED,
            code="unsupported_asset",
            reason="P0 supports SPL USDC payments, not native SOL transfers",
            recipient=recipient,
        )
    if not _valid_pubkey(mint):
        return _rejected(
            payload,
            protocol=PaymentProtocol.SOLANA_PAY,
            network="solana:unknown",
            confidence=IntentConfidence.INVALID,
            code="invalid_mint",
            reason="SPL token mint is not a valid public key",
            recipient=recipient,
        )

    known_asset = KNOWN_ASSETS.get(mint)
    if known_asset is None:
        return _rejected(
            payload,
            protocol=PaymentProtocol.SOLANA_PAY,
            network="solana:unknown",
            confidence=IntentConfidence.UNSUPPORTED,
            code="unsupported_asset",
            reason="Token mint is not in the P0 asset registry",
            recipient=recipient,
        )
    if not known_asset.enabled:
        return _rejected(
            payload,
            protocol=PaymentProtocol.SOLANA_PAY,
            network=known_asset.network,
            confidence=IntentConfidence.UNSUPPORTED,
            code="unsupported_network",
            reason="P0 executes payments on Solana Devnet only",
            recipient=recipient,
        )
    if amount_text is None or reference is None:
        missing = "amount" if amount_text is None else "reference"
        return _rejected(
            payload,
            protocol=PaymentProtocol.SOLANA_PAY,
            network=known_asset.network,
            confidence=IntentConfidence.INCOMPLETE,
            code=f"missing_{missing}",
            reason=f"Automatic payment requires an explicit {missing}",
            recipient=recipient,
        )
    if not _valid_pubkey(reference):
        return _rejected(
            payload,
            protocol=PaymentProtocol.SOLANA_PAY,
            network=known_asset.network,
            confidence=IntentConfidence.INVALID,
            code="invalid_reference",
            reason="Solana Pay reference is not a valid public key",
            recipient=recipient,
        )
    if DECIMAL_AMOUNT_PATTERN.fullmatch(amount_text) is None:
        return _rejected(
            payload,
            protocol=PaymentProtocol.SOLANA_PAY,
            network=known_asset.network,
            confidence=IntentConfidence.INVALID,
            code="invalid_amount",
            reason="Amount must be a non-negative plain decimal without exponent notation",
            recipient=recipient,
        )

    try:
        amount = TokenAmount.from_decimal(amount_text, decimals=known_asset.decimals)
    except (TypeError, ValueError) as exc:
        return _rejected(
            payload,
            protocol=PaymentProtocol.SOLANA_PAY,
            network=known_asset.network,
            confidence=IntentConfidence.INVALID,
            code="invalid_amount",
            reason=str(exc),
            recipient=recipient,
        )
    if amount.atomic == 0:
        return _rejected(
            payload,
            protocol=PaymentProtocol.SOLANA_PAY,
            network=known_asset.network,
            confidence=IntentConfidence.INCOMPLETE,
            code="non_positive_amount",
            reason="Automatic payment requires an amount greater than zero",
            recipient=recipient,
        )

    payload_hash = _hash_payload(payload)
    return PaymentIntent(
        intent_id=payload_hash,
        protocol=PaymentProtocol.SOLANA_PAY,
        network=known_asset.network,
        recipient=recipient,
        amount=amount,
        asset=PaymentAsset(
            symbol=known_asset.symbol,
            mint=known_asset.mint,
            decimals=known_asset.decimals,
        ),
        reference=reference,
        label=label,
        message=message,
        source_payload_hash=payload_hash,
        confidence=IntentConfidence.AUTHORITATIVE,
    )


def _resolve_non_solana(payload: str) -> PaymentIntent:
    parsed = urlsplit(payload)
    lowered = payload.lower()
    host = (parsed.hostname or "").lower()
    is_base_app_payment = (
        parsed.scheme.lower() == "https"
        and host == BASE_APP_PAYMENT_HOST
        and parsed.path.rstrip("/") == BASE_APP_PAYMENT_PATH
    )
    is_base = (
        parsed.scheme.lower() == "base"
        or host in BASE_PAYMENT_HOSTS
        or is_base_app_payment
        or any(f"@{chain_id}" in parsed.path for chain_id in BASE_CHAIN_IDS)
        or any(f"chainid={chain_id}" in lowered for chain_id in BASE_CHAIN_IDS)
    )
    if is_base:
        network = "eip155:84532" if ("84532" in lowered) else "eip155:8453"
        amount: TokenAmount | None = None
        asset: PaymentAsset | None = None
        if is_base_app_payment:
            query = parse_qs(parsed.query, keep_blank_values=True)
            try:
                amount_text = _single_query_value(query, "amount")
                asset_text = _single_query_value(query, "asset")
            except ValueError:
                amount_text = None
                asset_text = None

            if (
                amount_text is not None
                and asset_text is not None
                and asset_text.casefold() == "usdc"
                and DECIMAL_AMOUNT_PATTERN.fullmatch(amount_text) is not None
            ):
                try:
                    parsed_amount = TokenAmount.from_decimal(
                        amount_text, decimals=BASE_USDC_DECIMALS
                    )
                except (TypeError, ValueError):
                    parsed_amount = None
                if parsed_amount is not None and parsed_amount.atomic > 0:
                    amount = parsed_amount
                    asset = PaymentAsset(
                        symbol="USDC",
                        mint=None,
                        decimals=BASE_USDC_DECIMALS,
                    )
        return _rejected(
            payload,
            protocol=PaymentProtocol.BASE_PAY,
            network=network,
            confidence=IntentConfidence.UNSUPPORTED,
            code="unsupported_network",
            reason="Base payment requests cannot be executed by the Solana-only P0",
            amount=amount,
            asset=asset,
        )
    return _rejected(
        payload,
        protocol=PaymentProtocol.UNKNOWN,
        network="unknown",
        confidence=IntentConfidence.UNSUPPORTED,
        code="unsupported_protocol",
        reason="QR payload is not a supported Solana Pay transfer request",
    )


def resolve_payment_intent(payload: str) -> PaymentIntent:
    """Classify payment text without fetching URLs or inferring missing payment terms."""

    if not isinstance(payload, str):
        raise TypeError("payload must be a string")
    if not payload or len(payload) > 4096:
        return _rejected(
            payload,
            protocol=PaymentProtocol.UNKNOWN,
            network="unknown",
            confidence=IntentConfidence.INVALID,
            code="invalid_payload",
            reason="Payment payload must contain between 1 and 4096 characters",
        )

    parsed = urlsplit(payload)
    if parsed.scheme.lower() == "solana":
        return _resolve_solana_pay(payload)
    if _valid_pubkey(payload):
        return _rejected(
            payload,
            protocol=PaymentProtocol.RAW_ADDRESS,
            network="solana:unknown",
            confidence=IntentConfidence.INCOMPLETE,
            code="missing_payment_terms",
            reason=(
                "An address alone does not prove token, amount, network cluster, "
                "or order reference"
            ),
            recipient=payload,
        )
    return _resolve_non_solana(payload)
