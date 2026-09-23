import pytest

pytestmark = pytest.mark.urls("apps.core.tests.urls")


def get(api_client, query=""):
    return api_client.get(f"/api/v1/_t/numbers/{query}")


def test_first_page_shape_and_default_size(api_client):
    response = get(api_client)
    data = response.json()["data"]
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert set(data) == {"count", "next", "previous", "results"}
    assert data["count"] == 45 and len(data["results"]) == 30
    assert data["previous"] is None and "page=2" in data["next"]


def test_second_page(api_client):
    data = get(api_client, "?page=2").json()["data"]
    assert data["results"] == list(range(31, 46))
    assert data["next"] is None and data["previous"] is not None


def test_page_size_is_capped_at_120(api_client):
    assert len(get(api_client, "?page_size=1000").json()["data"]["results"]) == 45
    assert len(get(api_client, "?page_size=10").json()["data"]["results"]) == 10


def test_page_past_the_end_is_an_empty_200_not_a_404(api_client):
    response = get(api_client, "?page=9")
    data = response.json()["data"]
    assert response.status_code == 200
    assert data["results"] == [] and data["count"] == 45 and data["next"] is None
    assert "page=2" in data["previous"]  # points back at the real last page


def test_garbage_page_is_still_a_404_envelope(api_client):
    response = get(api_client, "?page=abc")
    assert response.status_code == 404
    assert response.json()["success"] is False
