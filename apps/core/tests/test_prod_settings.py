"""The production settings, loaded in a clean interpreter (the developer's `.env` is skipped on purpose, so what these
tests see never depends on the local file). Nothing here connects to a database."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[3]
STRONG_KEY = "k" * 20 + "".join(chr(97 + n % 26) + str(n) for n in range(40))  # 50+ characters, many different ones

PRINT_SETTINGS = """
import json
from django.conf import settings
from django.urls import reverse
import django
django.setup()
print(json.dumps({
    "num_proxies": settings.REST_FRAMEWORK["NUM_PROXIES"],
    "admin": reverse("admin:index"),
    "storage": settings.STORAGES["default"],
    "debug": settings.DEBUG,
    "max_upload_mb": settings.MAX_UPLOAD_REQUEST_MB,
}))
"""

CHECK_DEPLOY = """
import django
from django.core.management import execute_from_command_line
django.setup()
execute_from_command_line(["manage.py", "check", "--deploy", "--fail-level", "WARNING"])
"""


def prod(script, **env):
    """Run `script` with the production settings and a valid environment; `env` adds to it, and a value of None
    removes a variable."""
    code = "import environ\nenviron.Env.read_env = classmethod(lambda cls, *args, **kwargs: None)\n" + script
    clean = {
        key: value
        for key, value in os.environ.items()
        if key not in ("OTP_BACKEND", "DEBUG", "NUM_PROXIES", "ADMIN_URL", "MEDIA_STORAGE_BACKEND", "MEDIA_STORAGE_OPTIONS")
    }
    clean.update(
        DJANGO_SETTINGS_MODULE="config.settings.prod",
        SECRET_KEY=STRONG_KEY,
        DATABASE_URL="postgres://user:pass@127.0.0.1:5432/never_connected",
        ALLOWED_HOSTS="shop.example.com",
        CORS_ALLOWED_ORIGINS="https://shop.example.com",
        OTP_BACKEND="myshop.sms.RealProviderBackend",
        NUM_PROXIES="1",
    )
    for key, value in env.items():
        if value is None:
            clean.pop(key, None)
        else:
            clean[key] = value
    return subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND_DIR, env=clean, capture_output=True, text=True, timeout=90, check=False
    )


def printed(result):
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


# --- the deployment checklist ----------------------------------------------------------------------------------
def test_check_deploy_is_clean():
    result = prod(CHECK_DEPLOY)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no issues" in result.stdout


def test_check_deploy_is_still_clean_once_hsts_preload_is_switched_on():
    result = prod(CHECK_DEPLOY, SECURE_HSTS_PRELOAD="True")
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_deploy_notices_a_weak_secret_key():
    """The check itself is alive: it would fail the build if the settings regressed."""
    result = prod(CHECK_DEPLOY, SECRET_KEY="short")
    assert result.returncode != 0 and "security.W009" in result.stdout + result.stderr


# --- proxies -------------------------------------------------------------------------------------------------------
def test_the_number_of_proxies_must_be_stated():
    result = prod(PRINT_SETTINGS, NUM_PROXIES=None)
    assert result.returncode != 0
    assert "NUM_PROXIES" in result.stderr and "ImproperlyConfigured" in result.stderr


@pytest.mark.parametrize("value", ["0", "1", "2"])
def test_the_number_of_proxies_reaches_the_throttles(value):
    assert printed(prod(PRINT_SETTINGS, NUM_PROXIES=value))["num_proxies"] == int(value)


# --- the rest of the deployment knobs ------------------------------------------------------------------------------
def test_the_admin_can_be_moved_off_the_obvious_address():
    assert printed(prod(PRINT_SETTINGS))["admin"] == "/admin/"
    assert printed(prod(PRINT_SETTINGS, ADMIN_URL="staff-9f3k"))["admin"] == "/staff-9f3k/"
    assert printed(prod(PRINT_SETTINGS, ADMIN_URL="/staff-9f3k/"))["admin"] == "/staff-9f3k/"


def test_uploads_go_to_the_local_disk_unless_a_storage_is_named():
    assert printed(prod(PRINT_SETTINGS))["storage"] == {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {},
    }


def test_an_s3_compatible_storage_is_configured_from_the_environment():
    options = {"bucket_name": "gocart-media", "endpoint_url": "https://s3.example.com"}
    storage = printed(
        prod(
            PRINT_SETTINGS,
            MEDIA_STORAGE_BACKEND="storages.backends.s3.S3Storage",
            MEDIA_STORAGE_OPTIONS=json.dumps(options),
        )
    )["storage"]
    assert storage == {"BACKEND": "storages.backends.s3.S3Storage", "OPTIONS": options}


def test_the_upload_ceiling_covers_a_review_of_the_largest_files_and_can_be_changed():
    assert printed(prod(PRINT_SETTINGS))["max_upload_mb"] == 5 * 50 + 5  # MAX_REVIEW_FILES x MAX_VIDEO_UPLOAD_MB + 5
    assert printed(prod(PRINT_SETTINGS, MAX_UPLOAD_REQUEST_MB="20"))["max_upload_mb"] == 20


def test_debug_stays_off_whatever_the_environment_says():
    assert printed(prod(PRINT_SETTINGS, DEBUG="True"))["debug"] is False


def test_outside_production_there_is_no_proxy_by_default():
    """Local dev is reached directly, so nothing in X-Forwarded-For is to be believed."""
    dev = prod(PRINT_SETTINGS, DJANGO_SETTINGS_MODULE="config.settings.dev", NUM_PROXIES=None)
    assert printed(dev)["num_proxies"] == 0
