import pytest

from .helpers import set_charges


@pytest.fixture(autouse=True)
def _delivery_charges(db):
    """The migration seeds the two charges, but a transaction=True test flushes every table when it ends. Setting
    them here keeps each test independent of what ran before it."""
    set_charges()
