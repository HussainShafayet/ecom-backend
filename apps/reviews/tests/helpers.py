"""Shared by the reviews tests. `write_review` posts what the frontend's review form sends."""
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.accounts.models import User
from apps.accounts.tests.helpers import authed_client, verified_user  # noqa: F401  (authed_client is re-exported)
from apps.cart.tests.helpers import signed_in, stocked  # noqa: F401  (re-exported for the tests)
from apps.orders import services as order_services
from apps.orders.models import Order
from apps.orders.tests.helpers import line, make_order
from apps.reviews.models import Review

REVIEWS = "/api/v1/products/reviews/"
MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64


def image_upload(name="photo.png", fmt="PNG", size=(8, 8)):
    buffer = BytesIO()
    Image.new("RGB", size, "red").save(buffer, fmt)
    return SimpleUploadedFile(name, buffer.getvalue())


def video_upload(name="clip.mp4", data=MP4):
    return SimpleUploadedFile(name, data)


def deliver(order):
    """Move an order to delivered the way the staff do."""
    order_services.change_status(order, Order.Status.SHIPPED)
    order_services.change_status(order, Order.Status.DELIVERED)
    return order


def delivered_order(user, product, variant=None, quantity=1):
    """A delivered order of `user` that contains `product`."""
    return deliver(make_order(line(product, variant, quantity), user=user))


def buyer(product, variant, phone="+8801712345678"):
    """(user, client) of a customer whose order with `product` was delivered."""
    user, client = signed_in(phone)
    delivered_order(user, product, variant)
    return user, client


def other_customer(number):
    """A verified customer with a phone number of their own (no client)."""
    return verified_user(f"+88017000000{number:02d}")


def write_review(client, product, rating=5, comment="Really good.", media=(), **extra):
    body = {"product_id": product.pk, "rating": rating, "comment": comment, **extra}
    if media:
        body["media"] = list(media)
    return client.post(REVIEWS, body, format="multipart")


def edit_review(client, review_id, media=(), url=None, **fields):
    body = dict(fields)
    if media:
        body["media"] = list(media)
    return client.put(url or f"{REVIEWS}{review_id}/", body, format="multipart")


def review_by(user, product, rating=5, comment="Fine.", **extra):
    """A review written straight into the database (for tests that are not about the API)."""
    return Review.objects.create(product=product, user=user, rating=rating, comment=comment, **extra)


def reviewers(count, product, ratings):
    """`count` customers, each with a review of `product`; `ratings` is an iterable of their ratings."""
    users = [User.objects.create_user(f"+88018000{index:05d}", name=f"Customer {index}") for index in range(count)]
    for user, rating in zip(users, ratings):
        review_by(user, product, rating)
    return users


def data(response):
    return response.json()["data"]
