import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.catalog.tests.helpers import make_category, make_product
from apps.content.models import ContentItem, LinkType, Page, Placement
from apps.content.tests.helpers import make_item

pytestmark = pytest.mark.django_db

ITEM_KEYS = {"order", "type", "link", "external_link", "media", "media_type", "caption"}
CONTENT_KEYS = {"image_sliders", "video_sliders", "left_banner", "right_banner"}
# The exact spellings the frontend calls (contentService.js).
FRONTEND_PATHS = [
    "/api/v1/content/pages/home",
    "/api/v1/content/pages/newarrival/",
    "/api/v1/content/pages/flashsale",
    "/api/v1/content/pages/best_selling",
    "/api/v1/content/pages/feature",
    "/api/v1/content/pages/category",
]


def url(page="home"):
    return f"/api/v1/content/pages/{page}/"


def content(client, page="home"):
    response = client.get(url(page))
    assert response.status_code == 200, response.content
    return response.json()["data"]["page_content"]


# --- shape ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", FRONTEND_PATHS)
def test_every_page_the_frontend_asks_for_answers(api_client, path):
    body = api_client.get(path).json()
    assert body["success"] is True
    assert set(body["data"]) == {"page_content"}
    assert set(body["data"]["page_content"]) == CONTENT_KEYS


def test_a_page_nobody_filled_in_is_empty_not_an_error(api_client):
    assert content(api_client) == {"image_sliders": [], "video_sliders": [], "left_banner": None, "right_banner": None}


def test_a_missing_page_row_still_answers_empty(api_client):
    from apps.content.models import PageContent

    PageContent.objects.filter(page=Page.FEATURED).delete()
    assert content(api_client, "feature")["image_sliders"] == []


def test_an_unknown_page_is_a_404(api_client):
    response = api_client.get(url("nope"))
    assert response.status_code == 404
    assert response.json()["success"] is False


def test_item_has_exactly_the_fields_the_frontend_reads(api_client):
    product = make_product("Blue Shirt")
    make_item(placement=Placement.IMAGE_SLIDER, target=product, caption="Summer sale")

    item = content(api_client)["image_sliders"][0]

    assert set(item) == ITEM_KEYS
    assert item["order"] == 1
    assert item["type"] == "product"
    assert item["link"] == "blue-shirt"
    assert item["external_link"] is None
    assert item["media"].startswith("http://testserver/media/content/")
    assert item["media_type"] == "image"
    assert item["caption"] == "Summer sale"


def test_link_and_external_link_by_type(api_client):
    make_item(placement=Placement.IMAGE_SLIDER, order=1, target=make_product("Shirt"))
    make_item(placement=Placement.IMAGE_SLIDER, order=2, target=make_category("Shoes"))
    make_item(placement=Placement.IMAGE_SLIDER, order=3, link_type=LinkType.EXTERNAL, external_link="https://example.com/x")

    product, category, external = content(api_client)["image_sliders"]

    assert (product["type"], product["link"], product["external_link"]) == ("product", "shirt", None)
    assert (category["type"], category["link"], category["external_link"]) == ("category", "shoes", None)
    assert (external["type"], external["link"], external["external_link"]) == ("external", None, "https://example.com/x")


def test_no_caption_is_an_empty_string_the_frontend_can_test(api_client):
    make_item()
    assert content(api_client)["image_sliders"][0]["caption"] == ""


# --- placements ----------------------------------------------------------------------------------------
def test_items_land_in_their_own_slot(api_client):
    make_item(placement=Placement.IMAGE_SLIDER)
    make_item(placement=Placement.VIDEO_SLIDER, video=True)
    make_item(placement=Placement.LEFT_BANNER)
    make_item(placement=Placement.RIGHT_BANNER, video=True)

    data = content(api_client)

    assert len(data["image_sliders"]) == 1 and data["image_sliders"][0]["media_type"] == "image"
    assert len(data["video_sliders"]) == 1 and data["video_sliders"][0]["media_type"] == "video"
    assert isinstance(data["left_banner"], dict) and data["left_banner"]["media_type"] == "image"
    assert isinstance(data["right_banner"], dict) and data["right_banner"]["media_type"] == "video"


def test_pages_do_not_share_items(api_client):
    make_item(page=Page.HOME, placement=Placement.RIGHT_BANNER, caption="home banner")
    make_item(page=Page.FLASH_SALE, placement=Placement.IMAGE_SLIDER, caption="flash slide")

    assert content(api_client, "home")["image_sliders"] == []
    assert content(api_client, "home")["right_banner"]["caption"] == "home banner"
    assert content(api_client, "flashsale")["right_banner"] is None
    assert [i["caption"] for i in content(api_client, "flashsale")["image_sliders"]] == ["flash slide"]


def test_sliders_follow_the_admins_order_then_creation(api_client):
    make_item(order=2, caption="third")
    make_item(order=0, caption="first")
    make_item(order=1, caption="second")
    make_item(order=1, caption="second again")
    assert [i["caption"] for i in content(api_client)["image_sliders"]] == ["first", "second", "second again", "third"]


def test_order_is_one_two_three_even_when_every_stored_order_is_the_default(api_client):
    for _ in range(3):
        make_item()  # all stored as 0: the frontend's React key must still differ
    assert [i["order"] for i in content(api_client)["image_sliders"]] == [1, 2, 3]


def test_a_banner_is_one_object_not_a_list(api_client):
    make_item(placement=Placement.RIGHT_BANNER, order=5)
    banner = content(api_client)["right_banner"]
    assert isinstance(banner, dict) and banner["order"] == 1


# --- what is visible -------------------------------------------------------------------------------------
def test_inactive_items_are_hidden(api_client):
    make_item(caption="shown")
    make_item(caption="hidden", is_active=False)
    make_item(placement=Placement.RIGHT_BANNER, caption="old banner", is_active=False)
    data = content(api_client)
    assert [i["caption"] for i in data["image_sliders"]] == ["shown"]
    assert data["right_banner"] is None


def test_a_slide_to_a_hidden_product_or_category_is_left_out_until_it_is_back(api_client):
    product, category = make_product("Shirt"), make_category("Shoes")
    make_item(order=1, target=product, caption="product")
    make_item(order=2, target=category, caption="category")
    make_item(order=3, link_type=LinkType.EXTERNAL, external_link="https://example.com", caption="external")

    product.is_active = False
    product.save()
    category.is_active = False
    category.save()
    assert [i["caption"] for i in content(api_client)["image_sliders"]] == ["external"]

    product.is_active = True
    product.save()
    assert [i["caption"] for i in content(api_client)["image_sliders"]] == ["product", "external"]


def test_a_banner_to_a_hidden_product_is_null(api_client):
    product = make_product("Shirt", is_active=False)
    make_item(placement=Placement.RIGHT_BANNER, target=product)
    assert content(api_client)["right_banner"] is None


# --- access, cost ----------------------------------------------------------------------------------------
def test_public_and_both_slash_variants(api_client):
    make_item()
    for path in ("/api/v1/content/pages/home", "/api/v1/content/pages/home/"):
        response = api_client.get(path)
        assert response.status_code == 200, path
        assert len(response.json()["data"]["page_content"]["image_sliders"]) == 1


def test_one_query_however_many_items(api_client):
    def queries():
        with CaptureQueriesContext(connection) as context:
            assert api_client.get(url()).status_code == 200
        return len(context)

    for _ in range(2):
        make_item()
    small = queries()
    for _ in range(8):
        make_item(target=make_category(f"C{ContentItem.objects.count()}"))
        make_item(placement=Placement.VIDEO_SLIDER, video=True)
    assert queries() == small == 1
