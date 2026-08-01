"""Exact token amount types used by policies and Solana transactions."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_serializer

U64_MAX = (1 << 64) - 1


class TokenAmount(BaseModel):
    """A token amount stored in the token's indivisible atomic unit."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    atomic: int = Field(ge=0, le=U64_MAX)
    decimals: int = Field(ge=0, le=18)

    @field_serializer("atomic", when_used="json")
    def serialize_atomic_for_json(self, value: int) -> str:
        """Protect atomic units from JavaScript's limited safe-integer range."""

        return str(value)

    @classmethod
    def from_decimal(cls, value: str | Decimal, *, decimals: int) -> TokenAmount:
        """Convert a decimal string into atomic units without using binary floats."""

        if not isinstance(value, (str, Decimal)):
            raise TypeError("token amounts must be provided as str or Decimal")

        try:
            decimal_value = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("token amount is not a valid decimal") from exc

        if not decimal_value.is_finite():
            raise ValueError("token amount must be finite")
        if decimal_value < 0:
            raise ValueError("token amount cannot be negative")
        if not 0 <= decimals <= 18:
            raise ValueError("token decimals must be between 0 and 18")

        scale = Decimal(10) ** decimals
        scaled = decimal_value * scale
        if scaled != scaled.to_integral_value():
            raise ValueError(f"token amount exceeds {decimals} decimal places")

        return cls(atomic=int(scaled), decimals=decimals)

    def to_decimal(self) -> Decimal:
        """Return an exact decimal representation for calculation or display."""

        return Decimal(self.atomic).scaleb(-self.decimals)

    def to_display(self) -> str:
        """Return a non-exponential decimal string without insignificant zeroes."""

        rendered = format(self.to_decimal(), "f")
        if "." not in rendered:
            return rendered
        return rendered.rstrip("0").rstrip(".") or "0"
