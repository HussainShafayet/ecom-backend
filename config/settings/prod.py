"""Production settings. Every value that differs per deployment comes from the environment."""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

# Docs are off unless explicitly enabled.
ENABLE_API_DOCS = env.bool("ENABLE_API_DOCS", default=False)

# --- HTTPS / cookies -------------------------------------------------------------------------------
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
# Behind a reverse proxy that terminates TLS, set e.g. SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https
_proxy_header = env.tuple("SECURE_PROXY_SSL_HEADER", default=())
if _proxy_header:
    SECURE_PROXY_SSL_HEADER = _proxy_header
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# No default on purpose: a deployment without a real OTP delivery class must fail loudly at startup
# instead of silently printing codes to the log.
OTP_BACKEND = env("OTP_BACKEND")

# Throttle counters shared between worker processes (create the table once: manage.py createcachetable).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    }
}

# Keep DB connections open between requests.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)  # noqa: F405
