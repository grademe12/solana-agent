"""Schemas produced by the QR decoding boundary."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from packages.schemas.payment import Sha256Id


class DecodedPaymentQr(BaseModel):
    """Untrusted text extracted from exactly one QR code."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    format: Literal["qr_code"] = "qr_code"
    raw_payload: Annotated[str, StringConstraints(min_length=1, max_length=4096)]
    payload_hash: Sha256Id
    image_width: int = Field(gt=0, le=4096)
    image_height: int = Field(gt=0, le=4096)

