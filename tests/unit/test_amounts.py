from decimal import Decimal

import pytest
from pydantic import ValidationError

from packages.schemas import TokenAmount
from packages.schemas.amounts import U64_MAX


def test_usdc_decimal_converts_to_atomic_units() -> None:
    amount = TokenAmount.from_decimal("0.10", decimals=6)

    assert amount.atomic == 100_000
    assert amount.to_decimal() == Decimal("0.100000")
    assert amount.to_display() == "0.1"


def test_float_input_is_rejected() -> None:
    with pytest.raises(TypeError, match="str or Decimal"):
        TokenAmount.from_decimal(0.1, decimals=6)  # type: ignore[arg-type]


def test_excess_token_precision_is_rejected() -> None:
    with pytest.raises(ValueError, match="exceeds 6 decimal places"):
        TokenAmount.from_decimal("0.0000001", decimals=6)


def test_large_amount_remains_exact() -> None:
    amount = TokenAmount.from_decimal(Decimal("9007199254.740993"), decimals=6)

    assert amount.atomic == 9_007_199_254_740_993
    assert amount.model_dump(mode="json")["atomic"] == "9007199254740993"


def test_amount_above_solana_u64_limit_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TokenAmount(atomic=U64_MAX + 1, decimals=6)
