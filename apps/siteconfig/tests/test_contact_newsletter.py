import pytest

from apps.siteconfig.models import ContactMessage, NewsletterSubscriber

pytestmark = pytest.mark.django_db

CONTACT = "/api/v1/site/contact/"
NEWSLETTER = "/api/v1/site/newsletter/"
GOOD = {"name": "Rahim", "email": "rahim@example.com", "message": "Do you have this in blue?"}


def send(client, **fields):
    return client.post(CONTACT, {**GOOD, **fields}, format="json")


# --- contact form -------------------------------------------------------------------------------------------
def test_a_message_is_stored_for_the_staff(api_client):
    response = send(api_client, phone="+8801712345678", subject="Colour")
    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True and body["data"] is None and "Thank you" in body["message"]
    message = ContactMessage.objects.get()
    assert (message.name, message.email, message.phone, message.subject) == ("Rahim", "rahim@example.com", "+8801712345678", "Colour")
    assert message.message == "Do you have this in blue?" and message.is_handled is False


@pytest.mark.parametrize("path", ["/api/v1/site/contact", "/api/v1/site/contact/"])
def test_both_spellings_take_a_message(api_client, path):
    assert api_client.post(path, GOOD, format="json").status_code == 201


def test_phone_and_subject_are_optional(api_client):
    assert send(api_client).status_code == 201
    message = ContactMessage.objects.get()
    assert (message.phone, message.subject) == ("", "")


@pytest.mark.parametrize("missing", ["name", "email", "message"])
def test_name_email_and_message_are_required(api_client, missing):
    body = {key: value for key, value in GOOD.items() if key != missing}
    response = api_client.post(CONTACT, body, format="json")
    assert response.status_code == 400
    assert missing in response.json()["field_errors"]
    assert ContactMessage.objects.count() == 0


def test_a_wrong_email_is_refused(api_client):
    response = send(api_client, email="not-an-email")
    assert response.status_code == 400 and "email" in response.json()["field_errors"]


def test_a_message_can_not_be_empty_or_a_wall_of_text(api_client):
    assert send(api_client, message="   ").status_code == 400
    assert send(api_client, message="hi").status_code == 400  # shorter than 5 characters
    assert send(api_client, message="x" * 2001).status_code == 400
    assert send(api_client, message="x" * 2000).status_code == 201


def test_what_is_typed_is_trimmed_and_never_html_interpreted(api_client):
    send(api_client, name="  Rahim  ", message="  <script>alert(1)</script> hello  ")
    message = ContactMessage.objects.get()
    assert message.name == "Rahim"
    assert message.message == "<script>alert(1)</script> hello"  # stored as text: the admin escapes it when it shows it


def test_a_stale_token_does_not_turn_it_into_a_401(api_client):
    api_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")
    assert send(api_client).status_code == 201


def test_a_get_is_not_allowed(api_client):
    assert api_client.get(CONTACT).status_code == 405


def test_the_contact_form_is_rate_limited_per_client(api_client, settings):
    statuses = [send(api_client).status_code for _ in range(6)]
    assert statuses == [201] * 5 + [429]
    assert ContactMessage.objects.count() == 5


def test_a_refused_message_counts_against_the_limit_too(api_client):
    statuses = [send(api_client, email="bad").status_code for _ in range(6)]
    assert statuses == [400] * 5 + [429]


# --- newsletter ---------------------------------------------------------------------------------------------
def subscribe(client, email="rahim@example.com"):
    return client.post(NEWSLETTER, {"email": email}, format="json")


def test_an_address_is_added(api_client):
    response = subscribe(api_client)
    assert response.status_code == 200
    assert response.json()["message"] == "Thank you for subscribing." and response.json()["data"] is None
    assert list(NewsletterSubscriber.objects.values_list("email", "is_active")) == [("rahim@example.com", True)]


@pytest.mark.parametrize("path", ["/api/v1/site/newsletter", "/api/v1/site/newsletter/"])
def test_both_spellings_subscribe(api_client, path):
    assert api_client.post(path, {"email": "a@example.com"}, format="json").status_code == 200


def test_a_repeat_or_a_different_case_is_the_same_answer_and_one_row(api_client):
    first = subscribe(api_client, "Rahim@Example.com")
    again = subscribe(api_client, "rahim@example.com")
    assert (first.status_code, first.json()) == (again.status_code, again.json())  # nothing tells a stranger the address was listed
    assert NewsletterSubscriber.objects.count() == 1


def test_a_deactivated_address_that_subscribes_again_is_taken_back(api_client):
    NewsletterSubscriber.objects.create(email="rahim@example.com", is_active=False)
    subscribe(api_client)
    assert NewsletterSubscriber.objects.get().is_active is True


def test_a_wrong_or_missing_address_is_refused(api_client):
    assert subscribe(api_client, "nope").status_code == 400
    assert api_client.post(NEWSLETTER, {}, format="json").status_code == 400
    assert subscribe(api_client, "a" * 250 + "@example.com").status_code == 400
    assert NewsletterSubscriber.objects.count() == 0


def test_the_newsletter_is_rate_limited_per_client(api_client):
    statuses = [subscribe(api_client, f"user{n}@example.com").status_code for n in range(11)]
    assert statuses == [200] * 10 + [429]
    assert NewsletterSubscriber.objects.count() == 10
