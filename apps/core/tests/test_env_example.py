"""`.env.example` is the list of knobs a deployer reads: it must stay loadable and complete."""
import re
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[3]
EXAMPLE = (BACKEND_DIR / ".env.example").read_text()


def test_no_value_carries_an_inline_comment():
    """django-environ keeps `30/hour  # note` as the value, `int('255 # note')` fails and a rate quietly parses."""
    lines = [line for line in EXAMPLE.splitlines() if re.match(r"^[A-Z][A-Z0-9_]*=", line)]
    assert lines
    assert [line for line in lines if re.search(r"\s#", line)] == []


def test_every_environment_variable_the_settings_read_is_listed():
    """Uncommented or commented out, but written down."""
    listed = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", EXAMPLE, re.M))
    read = set()
    for module in (BACKEND_DIR / "config" / "settings").glob("*.py"):
        read |= set(re.findall(r'env(?:\.\w+)?\(\s*"([A-Z][A-Z0-9_]+)"', module.read_text()))
    assert read, "the pattern found no settings at all"
    assert sorted(read - listed) == []
