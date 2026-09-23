"""Settings shared by every environment. Environment-specific values come from `.env`."""
from datetime import timedelta
from pathlib import Path

import environ
from corsheaders.defaults import default_headers

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")  # real environment variables take precedence

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",  # refresh-token rotation + logout need it
    "drf_spectacular",
    # local
    "apps.core",
    "apps.accounts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",  # must sit above CommonMiddleware
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# PostgreSQL only (no SQLite, not even locally). DATABASE_URL=postgres://user:pass@127.0.0.1:5432/dbname
DATABASES = {"default": env.db("DATABASE_URL")}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [  # only staff have passwords (customers sign in with OTP)
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# The frontend calls both `/products` and `/products/` (and `/accounts/cart/`, ...). A 301 redirect would
# break CORS preflights that carry an Authorization header, so URLs are registered in both forms instead
# (see apps.core.urls.dual_path) and Django must never redirect.
APPEND_SLASH = False

# --- Django REST framework -------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["apps.core.renderers.EnvelopeJSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication"],
    # Secure by default: public endpoints must opt in with permission_classes = [AllowAny].
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.EnvelopePageNumberPagination",
    "EXCEPTION_HANDLER": "apps.core.exceptions.envelope_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Money is stored/computed as Decimal; the frontend does arithmetic and .toFixed() on the values,
    # so they go over the wire as JSON numbers, not strings.
    "COERCE_DECIMAL_TO_STRING": False,
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
    # Views opt in with throttle_classes = [ScopedRateThrottle] + throttle_scope. Rates are per client IP;
    # many users share one IP (mobile carrier NAT), so they are generous. The tight per-phone limits live
    # in apps.accounts.otp.service.
    "DEFAULT_THROTTLE_RATES": {
        "otp_send": env("THROTTLE_OTP_SEND", default="30/hour"),
        "otp_verify": env("THROTTLE_OTP_VERIFY", default="60/hour"),
        "token": env("THROTTLE_TOKEN", default="60/minute"),
    },
}

# DRF throttles live in the cache. LocMem is per-process (fine for dev); prod.py switches to a
# database cache so limits are shared between worker processes (run `createcachetable` once).
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# --- OTP (phone + one-time-code login) ---------------------------------------------------------------
# Delivery is pluggable: a class with send(target=, code=, purpose=). Dev prints the code to the server
# log; a real SMS/email provider is a new class + this setting.
OTP_BACKEND = env("OTP_BACKEND", default="apps.accounts.otp.backends.ConsoleOTPBackend")
OTP_LENGTH = 6
OTP_TTL_SECONDS = env.int("OTP_TTL_SECONDS", default=300)
OTP_MAX_ATTEMPTS = env.int("OTP_MAX_ATTEMPTS", default=5)
OTP_RESEND_COOLDOWN_SECONDS = env.int("OTP_RESEND_COOLDOWN_SECONDS", default=60)
OTP_MAX_RESENDS = env.int("OTP_MAX_RESENDS", default=3)
OTP_MAX_REQUESTS_PER_TARGET_PER_HOUR = env.int("OTP_MAX_REQUESTS_PER_TARGET_PER_HOUR", default=5)

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=30)),
    # The frontend stores the `refresh` returned by /accounts/token/refresh/ -> rotation is required.
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

ENABLE_API_DOCS = env.bool("ENABLE_API_DOCS", default=True)
SPECTACULAR_SETTINGS = {
    "TITLE": "GoCart API",
    "DESCRIPTION": "REST API for the GoCart storefront. Every response uses the "
    "`{success, message, data | errors}` envelope described in docs/API_CONTRACT.md.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "COMPONENT_SPLIT_REQUEST": True,  # separate request/response components (needed for file uploads)
    "PREPROCESSING_HOOKS": ["apps.core.schema.exclude_slashless_aliases"],
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        "apps.core.schema.envelope_postprocessing_hook",
    ],
}

# --- CORS ------------------------------------------------------------------------------------------
# Tokens travel in the Authorization header (not cookies), so credentials are not needed.
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_HEADERS = list(default_headers)
CORS_ALLOW_CREDENTIALS = False
CORS_URLS_REGEX = r"^/api/.*$"
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:3000")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
