import pytest

from apps.accounts.services import issue_tokens

from .helpers import post, verified_user

pytestmark = pytest.mark.django_db

STALE_ACCESS = {"HTTP_AUTHORIZATION": "Bearer an.expired.access-token"}


@pytest.fixture
def tokens():
    return issue_tokens(verified_user())


# --- token/refresh ------------------------------------------------------------------------------------
def test_refresh_rotates_and_returns_both_tokens_where_the_frontend_reads_them(api_client, tokens):
    # Exactly the frontend's call: body {expiresInMins, refresh} + the stale access token as Bearer.
    response = post(
        api_client, "token/refresh", {"expiresInMins": 1, "refresh": tokens["refresh"]}, **STALE_ACCESS
    )
    body = response.json()
    assert response.status_code == 200 and body["success"] is True
    assert body["data"]["access"] and body["data"]["refresh"]  # missing refresh would be stored as "undefined"
    assert body["data"]["refresh"] != tokens["refresh"]


def test_a_used_refresh_token_is_blacklisted(api_client, tokens):
    assert post(api_client, "token/refresh", {"refresh": tokens["refresh"]}).status_code == 200
    replay = post(api_client, "token/refresh", {"refresh": tokens["refresh"]})
    assert replay.status_code == 401
    assert replay.json()["success"] is False and isinstance(replay.json()["errors"], list)


def test_the_new_refresh_token_keeps_working(api_client, tokens):
    new = post(api_client, "token/refresh", {"refresh": tokens["refresh"]}).json()["data"]
    assert post(api_client, "token/refresh", {"refresh": new["refresh"]}).status_code == 200


def test_garbage_refresh_token_is_401(api_client):
    response = post(api_client, "token/refresh", {"refresh": "garbage"})
    assert response.status_code == 401
    assert response.json()["success"] is False


def test_refresh_token_is_required(api_client):
    response = post(api_client, "token/refresh", {})
    assert response.status_code == 400 and "refresh" in response.json()["field_errors"]


def test_refresh_for_a_disabled_user_is_401(api_client):
    user = verified_user("+8801755555555")
    pair = issue_tokens(user)
    user.is_active = False
    user.save()
    assert post(api_client, "token/refresh", {"refresh": pair["refresh"]}).status_code == 401


def test_refresh_for_a_deleted_user_is_401_not_a_500(api_client):
    user = verified_user("+8801766666666")
    pair = issue_tokens(user)
    user.delete()
    assert post(api_client, "token/refresh", {"refresh": pair["refresh"]}).status_code == 401


# --- logout -------------------------------------------------------------------------------------------
def test_logout_revokes_the_refresh_token(api_client, tokens):
    # The frontend sends {access, refresh} with the (possibly expired) access token as Bearer.
    response = post(api_client, "logout", tokens, **STALE_ACCESS)
    assert response.status_code == 200 and response.json()["success"] is True
    assert post(api_client, "token/refresh", {"refresh": tokens["refresh"]}).status_code == 401


def test_logout_is_idempotent_and_tolerant(api_client, tokens):
    assert post(api_client, "logout", tokens).status_code == 200
    assert post(api_client, "logout", tokens).status_code == 200  # already revoked
    assert post(api_client, "logout", {"refresh": "garbage"}).status_code == 200
    assert post(api_client, "logout", {}).status_code == 200  # cookie already gone
