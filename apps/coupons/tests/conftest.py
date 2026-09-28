import pytest

from apps.orders.tests.helpers import set_charges


@pytest.fixture(autouse=True)
def _delivery_charges(db):
    """The coupons concurrency tests place real orders through /orders/, which need a delivery charge. The
    migration seeds it, but a transaction=True test flushes every table when it ends — see
    apps/orders/tests/conftest.py, the same fixture, needed here too since this directory doesn't inherit it."""
    set_charges()
