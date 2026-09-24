"""Production settings. Every value that differs per deployment comes from the environment."""
from django.core.exceptions import ImproperlyConfigured

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
if not SECURE_HSTS_PRELOAD:
    # Joining the browsers' preload list is a one-way door (a domain is hard to remove again): opt in on purpose.
    SILENCED_SYSTEM_CHECKS = ["security.W021"]
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# No default on purpose: a deployment without a real OTP delivery class must fail loudly at startup
# instead of silently printing codes to the log.
OTP_BACKEND = env("OTP_BACKEND")
# BrowserOTPBackend puts the code in the API response. It also refuses to run without DEBUG; this makes a
# deployment that names it (under any module path) fail at startup instead of answering OTP requests with 503.
if OTP_BACKEND.strip().rsplit(".", 1)[-1] == "BrowserOTPBackend":
    raise ImproperlyConfigured(
        "OTP_BACKEND=BrowserOTPBackend is for local development only (it shows OTP codes in API responses) "
        "and is not allowed in production. Point OTP_BACKEND at a real SMS/email delivery class."
    )

# How many reverse proxies sit in front of Django (none = 0, nginx = 1, a CDN in front of nginx = 2). No default on
# purpose: 0 behind a proxy would throttle every customer as one address (the proxy's), and a number that is too
# high lets a client choose its own address with an X-Forwarded-For header and dodge every throttle.
REST_FRAMEWORK = {**REST_FRAMEWORK, "NUM_PROXIES": env.int("NUM_PROXIES")}  # noqa: F405

# Throttle counters shared between worker processes (create the table once: manage.py createcachetable).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    }
}

# Keep DB connections open between requests.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)  # noqa: F405
