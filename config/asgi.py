import os
from pathlib import Path

import environ
from django.core.asgi import get_asgi_application

environ.Env.read_env(Path(__file__).resolve().parent.parent / ".env")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_asgi_application()
