import pytest

from apps.core.utils import mask_email, mask_phone


def test_mask_phone_keeps_prefix_and_last_four():
    assert mask_phone("+8801712345678") == "+88017****5678"


@pytest.mark.parametrize("bad", [None, "", "123"])
def test_mask_phone_never_returns_short_or_empty_input(bad):
    assert mask_phone(bad) == "****"


def test_mask_email():
    assert mask_email("rahim@example.com") == "r***@example.com"
    assert mask_email("nope") == "****"
