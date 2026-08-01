"""Normalized payment intent schemas shared by QR and payment adapters."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from packages.schemas.amounts import TokenAmount

Sha256Id = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class PaymentProtocol(StrEnum):
    SOLANA_PAY = "solana_pay"
    BASE_PAY = "base_pay"
    RAW_ADDRESS = "raw_address"
    UNKNOWN = "unknown"


class IntentConfidence(StrEnum):
    AUTHORITATIVE = "authoritative"
    INCOMPLETE = "incomplete"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"


class PaymentAsset(BaseModel):
    """Token identity. The mint is authoritative; the symbol is display metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    symbol: str = Field(pattern=r"^[A-Z0-9]{2,12}$")
    mint: str | None = Field(default=None, min_length=1)
    decimals: int = Field(ge=0, le=18)


class PaymentIntent(BaseModel):
    """A protocol-neutral payment request that is safe to pass between tools."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    intent_id: Sha256Id
    protocol: PaymentProtocol
    network: str = Field(min_length=1, max_length=64)
    recipient: str | None = Field(default=None, min_length=1)
    amount: TokenAmount | None = None
    asset: PaymentAsset | None = None
    reference: str | None = Field(default=None, min_length=1)
    merchant_id: str | None = Field(default=None, min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=256)
    message: str | None = Field(default=None, max_length=512)
    expires_at: datetime | None = None
    source_payload_hash: Sha256Id
    confidence: IntentConfidence
    rejection_code: str | None = Field(default=None, min_length=1, max_length=64)
    rejection_reason: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_state(self) -> PaymentIntent:
        if self.expires_at is not None and self.expires_at.utcoffset() is None:
            raise ValueError("expires_at must include a timezone")

        if self.amount is not None and self.asset is None:
            raise ValueError("asset is required when amount is present")
        if (
            self.amount is not None
            and self.asset is not None
            and self.amount.decimals != self.asset.decimals
        ):
            raise ValueError("amount decimals must match asset decimals")

        if self.confidence is IntentConfidence.AUTHORITATIVE:
            required = {
                "recipient": self.recipient,
                "amount": self.amount,
                "asset": self.asset,
                "asset.mint": self.asset.mint if self.asset is not None else None,
                "reference": self.reference,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError(
                    "authoritative intent is missing required fields: " + ", ".join(missing)
                )
            if self.amount is not None and self.amount.atomic <= 0:
                raise ValueError("authoritative intent amount must be greater than zero")

        if self.confidence in {
            IntentConfidence.UNSUPPORTED,
            IntentConfidence.INVALID,
        } and (self.rejection_code is None or self.rejection_reason is None):
            raise ValueError("rejected intent requires a code and reason")

        return self

    @property
    def is_executable(self) -> bool:
        """Whether the normalized structure is complete enough for policy evaluation."""

        return self.confidence is IntentConfidence.AUTHORITATIVE

    @property
    def amount_display(self) -> str | None:
        """Render the atomic amount for UI and audit logs."""

        return self.amount.to_display() if self.amount is not None else None
