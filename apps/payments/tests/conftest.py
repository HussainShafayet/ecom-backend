import pytest

from apps.orders.tests.helpers import set_charges


@pytest.fixture(autouse=True)
def _delivery_charges(db):
    """Same as the orders tests: a transaction=True test flushes the seeded charges away."""
    set_charges()
