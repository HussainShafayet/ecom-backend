import pytest

from apps.orders.tests.helpers import set_charges


@pytest.fixture(autouse=True)
def _delivery_charges(db):
    """Reviews need delivered orders, and orders need a delivery charge. The migration seeds them, but a
    transaction=True test flushes every table when it ends, so each test sets them itself."""
    set_charges()
