import os
from pathlib import Path

import environ
from django.core.wsgi import get_wsgi_application

environ.Env.read_env(Path(__file__).resolve().parent.parent / ".env")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_wsgi_application()
