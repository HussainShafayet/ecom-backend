import pytest

from .helpers import make_faq, make_page

pytestmark = pytest.mark.django_db


def page(client, slug, **kwargs):
    return client.get(f"/api/v1/site/pages/{slug}/", **kwargs)


def test_a_published_page_is_answered_with_its_body(api_client):
    make_page("about-us", "About Us", "<h2>Story</h2><p>Since 2022</p>")
    response = page(api_client, "about-us")
    assert response.status_code == 200
    data = response.json()["data"]["page"]
    assert set(data) == {"slug", "title", "body", "updated_at"}
    assert (data["slug"], data["title"], data["body"]) == ("about-us", "About Us", "<h2>Story</h2><p>Since 2022</p>")


@pytest.mark.parametrize("path", ["/api/v1/site/pages/terms", "/api/v1/site/pages/terms/"])
def test_both_spellings_answer(api_client, path):
    make_page("terms", "Terms")
    assert api_client.get(path).status_code == 200


def test_an_unpublished_or_unknown_page_is_the_same_404(api_client):
    make_page("draft", "Draft", is_published=False)
    hidden = page(api_client, "draft")
    unknown = page(api_client, "nothing-here")
    assert hidden.status_code == unknown.status_code == 404
    assert hidden.json() == unknown.json()
    assert unknown.json()["success"] is False and unknown.json()["message"]


def test_a_page_is_found_by_its_exact_slug(api_client):
    make_page("about-us", "About Us")
    assert page(api_client, "About-Us").status_code == 404


def test_a_page_body_never_carries_a_script(api_client):
    make_page("clean", "Clean", "<p>ok</p><script>alert(1)</script>")
    assert page(api_client, "clean").json()["data"]["page"]["body"] == "<p>ok</p>"


def test_a_stale_token_is_not_a_401(api_client):
    make_page("about-us", "About Us")
    assert page(api_client, "about-us", HTTP_AUTHORIZATION="Bearer nope").status_code == 200


# --- FAQ ---------------------------------------------------------------------------------------------------
def test_the_faq_is_the_active_questions_in_order(api_client):
    make_faq("Second?", "b", category="Shipping", order=2)
    make_faq("First?", "a", category="Orders", order=1)
    make_faq("Hidden?", "c", is_active=False)
    response = api_client.get("/api/v1/site/faq/")
    assert response.status_code == 200
    assert response.json()["data"]["faqs"] == [
        {"category": "Orders", "question": "First?", "answer": "a"},
        {"category": "Shipping", "question": "Second?", "answer": "b"},
    ]


def test_a_question_without_a_category_is_general(api_client):
    make_faq("Where?", "Here.")
    assert api_client.get("/api/v1/site/faq").json()["data"]["faqs"][0]["category"] == "General"


def test_no_questions_is_an_empty_list_not_an_error(api_client):
    assert api_client.get("/api/v1/site/faq/").json()["data"] == {"faqs": []}
