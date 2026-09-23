from decimal import Decimal

import pytest

from apps.core.money import ZERO, quantize_money, to_decimal


def test_quantize_rounds_half_up():
    assert quantize_money("1.005") == Decimal("1.01")
    assert quantize_money("2.675") == Decimal("2.68")  # float math would give 2.67
    assert quantize_money(10) == Decimal("10.00")
    assert quantize_money(Decimal("0.999")) == Decimal("1.00")


def test_zero_constant_is_two_places():
    assert str(ZERO) == "0.00"


def test_string_input_is_stripped():
    assert to_decimal(" 12.50 ") == Decimal("12.50")


@pytest.mark.parametrize("bad", [1.5, True, None, [1]])
def test_floats_bools_and_other_types_are_refused(bad):
    with pytest.raises(TypeError):
        to_decimal(bad)


@pytest.mark.parametrize("bad", ["abc", "", "NaN", "Infinity", "-Infinity"])
def test_garbage_and_non_finite_are_refused(bad):
    with pytest.raises(ValueError):
        to_decimal(bad)
