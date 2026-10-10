"""Settings the tests run under: the development settings, but never reporting to a real Sentry project."""
import os

# Before `.base` is imported, which reads the environment first and `.env` second, and starts Sentry when a DSN is set. A developer's own
# `.env` may carry a live DSN for running the app locally; a test run must not send its (deliberately provoked) errors there.
os.environ["SENTRY_DSN"] = ""

from .dev import *  # noqa: E402,F401,F403
