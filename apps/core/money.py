"""The only place money arithmetic helpers live. Money is Decimal end to end; float is rejected."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MONEY_QUANT = Decimal("0.01")
ZERO = Decimal("0.00")


def to_decimal(value):
    """Convert str/int/Decimal to a finite Decimal. Floats (and bools) are refused on purpose."""
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("Money must be str, int or Decimal, never float.")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (int, str)):
        try:
            result = Decimal(str(value).strip())
        except InvalidOperation as exc:
            raise ValueError(f"Not a valid amount: {value!r}") from exc
    else:
        raise TypeError(f"Unsupported money type: {type(value).__name__}")
    if not result.is_finite():
        raise ValueError(f"Not a finite amount: {value!r}")
    return result


def quantize_money(value):
    """Round to 2 decimal places, half up (1.005 -> 1.01)."""
    return to_decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
