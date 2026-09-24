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
    "apps.addresses",
    "apps.catalog",
    "apps.content",
    "apps.wishlist",
    "apps.cart",
    "apps.orders",
    "apps.payments",
    "apps.reviews",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",  # must sit above CommonMiddleware
    "apps.core.middleware.UploadSizeLimitMiddleware",  # below CORS: its 413 must carry the CORS headers
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

# Uploaded files (profile pictures, reviews, ...). Dev: served from ./media by runserver. Prod: served by the reverse
# proxy or kept in an S3-compatible store (below); the API always returns absolute URLs.
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
# Where uploaded files are kept: the local MEDIA_ROOT by default. For S3 (or any S3-compatible store) install
# `django-storages[s3]` and set, for example,
#   MEDIA_STORAGE_BACKEND=storages.backends.s3.S3Storage
#   MEDIA_STORAGE_OPTIONS={"bucket_name": "...", "endpoint_url": "...", "access_key": "...", "secret_key": "..."}
# The API returns whatever URL the storage gives (absolute for S3, made absolute for the local disk).
STORAGES = {
    "default": {
        "BACKEND": env("MEDIA_STORAGE_BACKEND", default="django.core.files.storage.FileSystemStorage"),
        "OPTIONS": env.json("MEDIA_STORAGE_OPTIONS", default={}),
    },
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
MAX_IMAGE_UPLOAD_MB = env.int("MAX_IMAGE_UPLOAD_MB", default=5)
MAX_VIDEO_UPLOAD_MB = env.int("MAX_VIDEO_UPLOAD_MB", default=50)
MAX_REVIEW_FILES = env.int("MAX_REVIEW_FILES", default=5)  # photos + videos on one review
# The most one API upload request may weigh (the biggest legitimate one: a review of MAX_REVIEW_FILES videos, plus
# some room for the text fields). Bigger is answered with a 413 before it is read; see UploadSizeLimitMiddleware.
MAX_UPLOAD_REQUEST_MB = env.int("MAX_UPLOAD_REQUEST_MB", default=MAX_REVIEW_FILES * MAX_VIDEO_UPLOAD_MB + 5)
# Everything that is not an upload (JSON bodies, form fields): Django refuses more than this, see core/exceptions.py.
DATA_UPLOAD_MAX_MEMORY_SIZE = env.int("DATA_UPLOAD_MAX_MEMORY_SIZE", default=2_621_440)  # Django's own default, 2.5 MB

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
    # Every view is throttled by default, generously (a safety net against a runaway script or a hammering client:
    # a page of the shop makes ~10 calls). Views that need a tighter limit set throttle_classes =
    # [ScopedRateThrottle] + throttle_scope, which replaces these. Rates are per client IP, and many users share one IP
    # (mobile carrier NAT), so they are generous. The tight per-phone limits live in apps.accounts.otp.service.
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    # How many reverse proxies sit between the internet and Django: 0 = the app is reached directly (dev). With a
    # proxy the client is the address that proxy appended to X-Forwarded-For, and DRF must be told how many proxies to
    # trust: left unset it would take the whole (client-controlled) header as the "IP", and a client could dodge every
    # throttle by sending a new header value with each request. prod.py makes this setting mandatory.
    "NUM_PROXIES": env.int("NUM_PROXIES", default=0),
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON", default="600/minute"),  # a guest, per IP
        "user": env("THROTTLE_USER", default="1200/minute"),  # a signed-in customer
        "otp_send": env("THROTTLE_OTP_SEND", default="30/hour"),
        "otp_verify": env("THROTTLE_OTP_VERIFY", default="60/hour"),
        "token": env("THROTTLE_TOKEN", default="60/minute"),
        "order": env("THROTTLE_ORDER", default="30/hour"),
        "order_track": env("THROTTLE_ORDER_TRACK", default="30/hour"),  # a guest looking an order up, per IP; misses count
        "review": env("THROTTLE_REVIEW", default="30/hour"),  # per signed-in customer: writing or editing a review
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
# After verifying a new phone/email with an OTP the user has this long to save it on the profile.
PROFILE_VERIFICATION_WINDOW_SECONDS = env.int("PROFILE_VERIFICATION_WINDOW_SECONDS", default=900)

# --- shop ---------------------------------------------------------------------------------------------
MAX_ADDRESSES_PER_USER = env.int("MAX_ADDRESSES_PER_USER", default=20)
MAX_CART_LINES = env.int("MAX_CART_LINES", default=50)  # different products/variants in one cart
MAX_FAVOURITES_PER_USER = env.int("MAX_FAVOURITES_PER_USER", default=200)
# Order numbers read <prefix>-YYYYMMDD-NNNN (letters and digits only: the number goes into the confirmation URL).
ORDER_NUMBER_PREFIX = env("ORDER_NUMBER_PREFIX", default="GC")

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
    # Product media and content items both say image|video: one schema name for that choice set.
    "ENUM_NAME_OVERRIDES": {"MediaTypeEnum": "apps.content.models.MediaType"},
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

# Where the Django admin lives. Change it in production (`ADMIN_URL=staff-9f3k/`) so the staff login is not the first
# thing every scanner finds. A leading slash is ignored; the trailing one is added.
ADMIN_URL = env("ADMIN_URL", default="admin/").strip("/") + "/"

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
