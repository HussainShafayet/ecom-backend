#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path

import environ


def main():
    # Read .env first so DJANGO_SETTINGS_MODULE can be set there (real env vars still win).
    environ.Env.read_env(Path(__file__).resolve().parent / ".env")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Is the virtualenv active? "
            "(cd backend && source venv/bin/activate)"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
