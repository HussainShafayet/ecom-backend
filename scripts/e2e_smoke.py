"""End-to-end smoke test: one customer's whole visit, replayed against a RUNNING dev server the way the React shop makes
it (same calls, same spelling, same payloads: config/frontend_calls.py lists them, ecom/src is the source).

    source venv/bin/activate
    python manage.py runserver                     # another terminal; .env needs OTP_BACKEND=...BrowserOTPBackend
    python scripts/e2e_smoke.py [--server http://127.0.0.1:8000] [--origin http://localhost:3000]

What it does: browses as a guest, places a guest order, signs up (OTP), merges a guest cart and favourites, edits the
profile (picture, e-mail with its own OTP) and addresses, works the cart and wishlist, checks out, has the order
delivered (the one staff step, done through `orders.services.change_status`), reviews the product with a photo and a
video, edits the review the way the frontend does, refreshes and revokes its tokens. Every response is checked for the
envelope and for the CORS header the browser needs; at the end every call in `FRONTEND_CALLS` must have been made.

DEV ONLY. It writes to the database of the settings it loads (`config.settings.dev`), through a throw-away customer
and two products, and puts every counter, file and row back afterwards. Exit status 1 when a check fails.
"""
import argparse
import glob
import io
import json
import os
import random
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from PIL import Image  # noqa: E402

from apps.accounts.models import User  # noqa: E402
from apps.catalog.models import Product, ProductVariant  # noqa: E402
from apps.orders import services as order_services  # noqa: E402
from apps.orders.models import Order  # noqa: E402
from apps.reviews.models import Review  # noqa: E402
from config.frontend_calls import FRONTEND_CALLS, api_path  # noqa: E402

MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64
HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64
CODE = re.compile(r"\[DEV\] Your code is (\d{6})")

checks, calls_made, covered, problems = [], 0, set(), []


def png(color="blue"):
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buffer, "PNG")
    return buffer.getvalue()


def ok(label, condition, detail=""):
    checks.append((label, bool(condition)))
    print(("  PASS  " if condition else "  FAIL  ") + label + (f"    [{str(detail)[:230]}]" if detail and not condition else ""))
    return bool(condition)


def phase(title):
    print(f"\n== {title}")


class Client:
    def __init__(self, server, origin):
        self.server, self.origin = server.rstrip("/"), origin

    def call(self, method, template, *, token=None, query="", body=None, fields=None, files=None, raw=False, **params):
        """One call of the frontend: `template` is how ecom/src spells it. Returns (status, json | bytes, headers)."""
        global calls_made
        path = api_path(template, **params) + (f"?{query}" if query else "")
        headers = {"Origin": self.origin}
        data = None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        elif fields is not None or files:
            boundary = uuid.uuid4().hex
            out = io.BytesIO()
            for name, value in fields or []:
                out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
            for name, filename, content_type, content in files or []:
                out.write(
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                    f"Content-Type: {content_type}\r\n\r\n".encode() + content + b"\r\n"
                )
            out.write(f"--{boundary}--\r\n".encode())
            data, headers["Content-Type"] = out.getvalue(), f"multipart/form-data; boundary={boundary}"
        request = urllib.request.Request(self.server + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request) as response:
                status, payload, response_headers = response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            status, payload, response_headers = error.code, error.read(), error.headers
        calls_made += 1
        covered.add((method, template))
        parsed = json.loads(payload) if not raw and payload else payload
        self.audit(method, path, status, parsed, response_headers)
        return status, parsed, response_headers

    def audit(self, method, path, status, parsed, headers):
        """What every response must satisfy, whatever the call: the CORS header and the envelope."""
        where = f"{method} {path} -> {status}"
        if headers.get("Access-Control-Allow-Origin") != self.origin:
            problems.append(f"{where}: no CORS header for {self.origin}")
        if not isinstance(parsed, dict):
            problems.append(f"{where}: the body is not a JSON object")
            return
        if not isinstance(parsed.get("success"), bool):
            problems.append(f"{where}: no boolean `success`")
        elif parsed["success"] and not {"message", "data"} <= parsed.keys():
            problems.append(f"{where}: a success without message and data")
        elif not parsed["success"] and not (isinstance(parsed.get("errors"), list) and isinstance(parsed.get("error"), str)):
            problems.append(f"{where}: an error without `error` (string) and `errors` (list)")

    def fetch(self, url):
        with urllib.request.urlopen(url) as response:
            return response.status, response.read(), response.headers


def code_of(response_body):
    found = CODE.search(response_body.get("message", ""))
    return found.group(1) if found else None


def checkout_body(cards_and_quantities, phone="+8801712345678", **extra):
    """What Checkout.js posts, with prices the server must ignore."""
    body = {
        "name": "Smoke Tester", "email": "", "shipping_type": "inside_dhaka", "shipping_area": "Gulshan",
        "phone_number": phone, "shipping": None, "shipping_division": "", "shipping_district": "",
        "shipping_thana": "", "shipping_address": "House 1, Road 2", "payment_type": "cash",
        "items": [{"product_id": c["id"], "variant_id": c["variant_id"], "quantity": q, "price": 1} for c, q in cards_and_quantities],
        "sub_total_price": "1.00", "delivery_charge": 1, "total_price": "2.00",
    }
    body.update(extra)
    return body


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--origin", default="http://localhost:3000", help="the frontend's origin (CORS)")
    args = parser.parse_args()
    if not settings.DEBUG:
        sys.exit("Refusing to run: this writes test data. Use the development settings (DEBUG=True).")

    api = Client(args.server, args.origin)
    phone = f"+88019{random.randrange(10**8):08d}"
    email = f"smoke.{uuid.uuid4().hex[:8]}@example.com"
    media_before = set(glob.glob(str(settings.MEDIA_ROOT / "**" / "*"), recursive=True))
    order_ids, user = [], None
    saved = {}

    try:
        # ------------------------------------------------------------------------------------------------------
        phase("Guest: browse the shop (publicApi, no token)")
        for template in ("/content/pages/home", "/content/pages/newarrival/", "/content/pages/flashsale",
                         "/content/pages/best_selling", "/content/pages/feature", "/content/pages/category", "/content/shop"):
            status, body, _ = api.call("GET", template)
            ok(f"GET {template} -> 200", status == 200, body)
        for template in ("/products/categories", "/products/categories/flash-sale/", "/products/categories/new-arrival/",
                         "/products/categories/best-selling/", "/products/categories/feature/"):
            status, body, _ = api.call("GET", template, query="page=1&page_size=8")
            ok(f"GET {template} -> 200", status == 200, body)
        status, body, _ = api.call("GET", "/products", query="page=1&page_size=60")
        cards = body["data"]["results"] if status == 200 else []
        ok("GET /products -> 200 with product cards", status == 200 and cards, body)
        for template in ("/products/new-arrivals", "/products/best-selling", "/products/flash-sale", "/products/featured"):
            status, body, _ = api.call("GET", template, query="page=1&page_size=12")
            ok(f"GET {template} -> 200", status == 200, body)

        chosen = []
        for card in cards:
            variant = ProductVariant.objects.filter(pk=card.get("variant_id")).select_related("product").first()
            if variant and card["availability_status"] and variant.stock_quantity >= 8 and variant.product.minimum_order_quantity == 1 \
                    and variant.is_active and card["id"] not in [c["id"] for c in chosen]:
                chosen.append(card)
            if len(chosen) == 2:
                break
        if len(chosen) < 2:
            sys.exit("Need two available products (stock >= 8, minimum order 1) in the dev database: run `seed_catalog`.")
        first, second = chosen
        for card in chosen:  # remember what the run will touch, to put it back
            product = Product.objects.get(pk=card["id"])
            saved[card["id"]] = {
                "variant": card["variant_id"], "stock": ProductVariant.objects.get(pk=card["variant_id"]).stock_quantity,
                "orders": product.total_orders, "reviews": product.total_reviews, "rating": product.avg_rating,
            }

        status, body, _ = api.call("GET", "/products/detail/{slug}", slug=first["slug"])
        ok("GET /products/detail/{slug} (no trailing slash) -> 200", status == 200 and body["data"]["id"] == first["id"], body)
        status, body, _ = api.call("GET", "/products/search-suggestions/", query=f"q={first['name'][:3]}")
        ok("GET /products/search-suggestions/?q= -> a list of names", status == 200 and isinstance(body["data"], list), body)
        status, body, _ = api.call("GET", "products/reviews/", query=f"product_id={first['id']}")
        ok("GET products/reviews/ as a guest -> can_review false", status == 200 and body["data"]["can_review"] is False, body)
        status, body, _ = api.call("GET", "/content/checkout/")
        ok("GET /content/checkout/ as a guest -> delivery charges, no user_info",
           status == 200 and {"inside_dhaka", "outside_dhaka"} <= body["data"]["delivery_charges"].keys() and body["data"]["user_info"] is None, body)

        phase("Guest: place an order (publicApi); the prices the client sends are ignored")
        status, body, _ = api.call("POST", "/orders/", body=checkout_body([(first, 1)]))
        ok("POST /orders/ as a guest -> 201 with an order number", status == 201 and body["data"]["order_id"].startswith("GC-"), body)
        if status == 201:
            guest_order = Order.objects.get(number=body["data"]["order_id"])
            order_ids.append(guest_order.pk)
            ok("the guest order has no customer and the server's prices", guest_order.user is None and guest_order.subtotal > 1 and guest_order.total == guest_order.subtotal + guest_order.delivery_charge, guest_order.total)

            track_query = f"order_id={guest_order.number.lower()}&phone_number=%2B8801712345678"  # typed in lower case
            status, body, _ = api.call("GET", "/orders/track/", query=track_query)
            private = ("Smoke Tester", "House 1", "+8801712345678", "Gulshan")
            ok("GET /orders/track/ as a guest: progress and items, nothing about who or where",
               status == 200 and body["data"]["status"] == "pending" and body["data"]["items"] and not any(text in json.dumps(body) for text in private), body)
            status, body, _ = api.call("GET", "/orders/track/", query=f"order_id={guest_order.number}&phone_number=%2B8801799999999")
            ok("a wrong phone number is a 404 (the same answer as an unknown order)", status == 404 and body["error"] == "No order matches these details.", body)

        # ------------------------------------------------------------------------------------------------------
        phase("Sign up: register, OTP, merge of the guest cart and favourites")
        status, body, _ = api.call("POST", "/accounts/register/", body={"phone_number": phone, "email": email, "name": "Smoke Tester"})
        otp, sign_up_token = code_of(body), body.get("data", {}).get("token") if status == 200 else None
        if not (ok("POST /accounts/register/ -> 200 with a token", status == 200 and sign_up_token, body)
                and ok("the dev server shows the OTP in `message` (OTP_BACKEND=...BrowserOTPBackend)", otp, body.get("message"))):
            sys.exit("Cannot go on without the OTP: start the server with OTP_BACKEND=apps.accounts.otp.backends.BrowserOTPBackend.")
        status, body, headers = api.call("POST", "/accounts/resend-otp/", body={"token": sign_up_token})
        ok("POST /accounts/resend-otp/ straight away -> 429 (cooldown) with Retry-After", status == 429 and headers.get("Retry-After"), body)
        status, body, _ = api.call("POST", "/accounts/verify-otp/", body={"token": sign_up_token, "otp": "000000" if otp != "000000" else "111111", "cart": [], "favorite": []})
        ok("a wrong OTP -> 400 (never 401)", status == 400, body)
        guest_cart = [{"product_id": first["id"], "quantity": 2, "variant_id": first["variant_id"]},
                      {"product_id": second["id"], "quantity": 1, "variant_id": second["variant_id"]}]
        status, body, _ = api.call("POST", "/accounts/verify-otp/", body={"token": sign_up_token, "otp": otp, "cart": guest_cart, "favorite": [{"product_id": first["id"]}]})
        tokens = body.get("data", {}).get("tokens", {}) if status == 200 else {}
        if not ok("POST /accounts/verify-otp/ with the guest cart -> 200 and a token pair", status == 200 and tokens.get("access") and tokens.get("refresh"), body):
            sys.exit("Cannot go on without a token pair.")
        access, refresh = tokens["access"], tokens["refresh"]
        user = User.objects.get(phone_number=phone)
        status, body, _ = api.call("GET", "/accounts/cart/", token=access)
        ok("the guest cart was merged (2 lines, quantities 2 and 1)", status == 200 and sorted((i["id"], i["quantity"]) for i in body["data"]) == sorted([(first["id"], 2), (second["id"], 1)]), body)
        status, body, _ = api.call("GET", "/accounts/favourite/", token=access)
        ok("the guest favourite was merged", status == 200 and [i["id"] for i in body["data"]] == [first["id"]], body)

        phase("Sign in again (login -> OTP -> verify), as on the next visit")
        status, body, _ = api.call("POST", "/accounts/login/", body={"phone_number": phone})
        login_token, login_otp = body.get("data", {}).get("token"), code_of(body)
        ok("POST /accounts/login/ -> 200, token and OTP", status == 200 and login_token and login_otp, body)
        status, body, _ = api.call("POST", "/accounts/verify-otp/", body={"token": login_token, "otp": login_otp, "cart": [], "favorite": []})
        tokens = body.get("data", {}).get("tokens", {}) if status == 200 else {}
        ok("verify-otp after login -> a new token pair", status == 200 and tokens.get("access"), body)
        access, refresh = tokens.get("access", access), tokens.get("refresh", refresh)

        phase("Signed in: browse (api with a token)")
        status, body, _ = api.call("GET", "/products", token=access, query="page=1&page_size=60")
        flagged = [c["is_favourite"] for c in body["data"]["results"] if c["id"] == first["id"]]
        ok("the product list knows my favourite (is_favourite)", status == 200 and flagged == [True], body)
        status, body, _ = api.call("GET", "/products/search-suggestions/", token=access, query="q=sh")
        ok("search suggestions with a token -> 200", status == 200, body)
        status, body, _ = api.call("GET", "products/reviews/", token=access, query=f"product_id={first['id']}")
        ok("reviews before the order exists: can_review false, not_purchased", status == 200 and body["data"]["can_review"] is False and body["data"]["review_status"] == "not_purchased", body)
        status, body, _ = api.call("GET", "/content/checkout/", token=access)
        ok("checkout content for me: my name and phone", status == 200 and body["data"]["user_info"]["phone_number"] == phone, body)

        phase("Profile: details, picture, an e-mail change with its own OTP")
        status, body, _ = api.call("GET", "/accounts/profile/", token=access)
        ok("GET /accounts/profile/ -> my details", status == 200 and body["data"]["phone_number"] == phone and body["data"]["name"] == "Smoke Tester", body)
        status, body, _ = api.call("PUT", "/accounts/profile/", token=access, fields=[("name", "Smoke Renamed"), ("gender", "male"), ("date_of_birth", "1990-05-17")],
                                   files=[("profile_picture", "me.png", "image/png", png("green"))])
        picture = (body.get("data") or {}).get("profile_picture") if status == 200 else None
        ok("PUT /accounts/profile/ (multipart, only the changed fields + a picture) -> 200", status == 200 and body["data"]["name"] == "Smoke Renamed" and picture, body)
        if picture:
            status, content, headers = api.fetch(picture)
            ok("the profile picture is an absolute URL that serves the image", status == 200 and headers.get_content_type().startswith("image/"), picture)
        status, body, _ = api.call("PUT", "/accounts/profile/", token=access, fields=[("email", f"other.{email}")])
        ok("a new e-mail is refused until it is verified -> 400", status == 400, body)
        status, body, _ = api.call("POST", "accounts/request-otp/", token=access, body={"email": f"new.{email}"})
        change_token, change_otp = body.get("data", {}).get("token"), code_of(body)
        ok("POST accounts/request-otp/ (e-mail) -> token and OTP", status == 200 and change_token and change_otp, body)
        status, body, _ = api.call("POST", "accounts/verify-otp-for-profile/", token=access, body={"token": change_token, "otp": change_otp})
        ok("POST accounts/verify-otp-for-profile/ -> verified", status == 200, body)
        status, body, _ = api.call("PUT", "/accounts/profile/", token=access, fields=[("email", f"new.{email}")])
        ok("the verified e-mail is saved", status == 200 and body["data"]["email"] == f"new.{email}", body)

        phase("Addresses")
        address = {"title": "Home", "shipping_type": "inside_dhaka", "address": "House 1, Road 2", "area": "Gulshan", "division": "Dhaka", "district": "Dhaka", "thana": "Gulshan"}
        status, body, _ = api.call("POST", "/accounts/addresses/", token=access, body=address)
        address_id = (body.get("data") or {}).get("id")
        ok("POST /accounts/addresses/ -> 201", status == 201 and address_id, body)
        status, body, _ = api.call("GET", "/accounts/addresses/", token=access)
        ok("GET /accounts/addresses/ -> a plain array with it", status == 200 and [a["id"] for a in body["data"]] == [address_id], body)
        status, body, _ = api.call("GET", "/content/checkout/", token=access)
        ok("checkout content lists the saved address", status == 200 and [a["id"] for a in body["data"]["shipping_addresses"]] == [address_id], body)
        status, body, _ = api.call("PUT", "/accounts/addresses/{id}/", token=access, body={**address, "id": address_id, "title": "Office"}, id=address_id)
        ok("PUT /accounts/addresses/{id}/ (the whole object, id included) -> 200", status == 200 and body["data"]["title"] == "Office", body)
        status, body, _ = api.call("DELETE", "/accounts/addresses/{id}/", token=access, id=address_id)
        ok("DELETE /accounts/addresses/{id}/ -> 200", status == 200, body)
        status, body, _ = api.call("GET", "/accounts/addresses/", token=access)
        ok("the address list is empty again", status == 200 and body["data"] == [], body)

        phase("Cart and wishlist")
        line = lambda card, quantity, action: {"product_id": card["id"], "quantity": quantity, "variant_id": card["variant_id"], "action": action}  # noqa: E731
        status, body, _ = api.call("POST", "/accounts/cart/", token=access, body=line(first, 1, "increase"))
        ok("POST /accounts/cart/ increase 1 -> 200", status == 200, body)
        status, body, _ = api.call("POST", "/accounts/cart/", token=access, body=line(first, 1, "decrease"))
        status, cart, _ = api.call("GET", "/accounts/cart/", token=access)
        ok("increase then decrease leaves quantity 2 (a delta, not a total)", dict((i["id"], i["quantity"]) for i in cart["data"]).get(first["id"]) == 2, cart)
        status, body, _ = api.call("POST", "/accounts/cart/", token=access, body=line(first, 9999, "increase"))
        ok("more than the stock -> 400 with a sentence", status == 400 and body["error"], body)
        status, body, _ = api.call("PUT", "/accounts/cart/", token=access, body={"product_id": second["id"], "variant_id": second["variant_id"]})
        status, cart, _ = api.call("GET", "/accounts/cart/", token=access)
        ok("PUT /accounts/cart/ (one object) removed a line", [i["id"] for i in cart["data"]] == [first["id"]], cart)
        api.call("POST", "/accounts/cart/", token=access, body=line(second, 1, "increase"))
        status, body, _ = api.call("PUT", "/accounts/cart/", token=access, body=[{"product_id": first["id"], "variant_id": first["variant_id"]}, {"product_id": second["id"], "variant_id": second["variant_id"]}])
        status, cart, _ = api.call("GET", "/accounts/cart/", token=access)
        ok("PUT /accounts/cart/ (an array) emptied the cart", status == 200 and cart["data"] == [], cart)
        api.call("POST", "/accounts/cart/", token=access, body=line(first, 2, "increase"))
        api.call("POST", "/accounts/cart/", token=access, body=line(second, 1, "increase"))
        status, body, _ = api.call("POST", "/accounts/favourite/", token=access, body={"product_id": second["id"]})
        status, fav, _ = api.call("GET", "/accounts/favourite/", token=access)
        ok("POST /accounts/favourite/ then GET -> two favourites", sorted(i["id"] for i in fav["data"]) == sorted([first["id"], second["id"]]), fav)
        status, body, _ = api.call("PUT", "/accounts/favourite/", token=access, body={"product_id": second["id"]})
        status, fav, _ = api.call("GET", "/accounts/favourite/", token=access)
        ok("PUT /accounts/favourite/ removed one", [i["id"] for i in fav["data"]] == [first["id"]], fav)

        phase("Checkout as a signed-in customer")
        status, cart, _ = api.call("GET", "/accounts/cart/", token=access)
        outside = {"shipping_type": "outside_dhaka", "shipping_area": "", "shipping_division": "Chattogram",
                   "shipping_district": "Cumilla", "shipping_thana": "Debidwar"}  # what Checkout.js fills in outside Dhaka
        status, body, _ = api.call("POST", "/orders/", token=access, body=checkout_body([(c, c["quantity"]) for c in cart["data"]], phone=phone, **outside))
        if not ok("POST /orders/ with a token -> 201", status == 201 and body["data"]["order_id"].startswith("GC-"), body):
            sys.exit("Cannot go on without the order.")
        order = Order.objects.get(number=body["data"]["order_id"])
        order_ids.append(order.pk)
        ok("the order belongs to me, is pending, and was priced by the server", order.user_id == user.pk and order.status == "pending" and order.total == order.subtotal + order.delivery_charge and order.delivery_charge > 1, order.total)
        ok("the outside-Dhaka delivery charge was applied", order.shipping_type == "outside_dhaka", order.shipping_type)
        ok("its cash-on-delivery payment is pending", list(order.payments.values_list("status", flat=True)) == ["pending"], list(order.payments.values_list("status", flat=True)))
        status, cart, _ = api.call("GET", "/accounts/cart/", token=access)
        ok("the ordered lines left my cart", status == 200 and cart["data"] == [], cart)
        ok("stock went down and the products counted the sale", all(ProductVariant.objects.get(pk=v["variant"]).stock_quantity < v["stock"] and Product.objects.get(pk=pk).total_orders > v["orders"] for pk, v in saved.items()))

        status, body, _ = api.call("GET", "products/reviews/", token=access, query=f"product_id={first['id']}")
        ok("ordered but not delivered: waiting_for_delivery, and the order to link to",
           status == 200 and body["data"]["can_review"] is False and body["data"]["review_status"] == "waiting_for_delivery" and body["data"]["order_id"] == order.number, body)

        phase("My orders: list, detail, cancel")
        status, body, _ = api.call("GET", "/orders/", token=access)
        rows = body["data"]["results"] if status == 200 else []
        ok("GET /orders/ -> only my order (the guest order is nobody's), with its units and lines",
           status == 200 and [r["order_id"] for r in rows] == [order.number] and rows[0]["items_count"] == 3 and len(rows[0]["items"]) == 2, body)
        status, body, _ = api.call("GET", "/orders/{number}/", token=access, number=order.number)
        detail = body.get("data") or {}
        ok("GET /orders/{number}/ -> address, totals, pending payment, history, can_cancel",
           status == 200 and detail["shipping_address"] == "House 1, Road 2" and detail["total"] == float(order.total) and detail["payment"]["status"] == "pending"
           and [h["status"] for h in detail["history"]] == ["pending"] and detail["can_cancel"] is True, body)
        ok("every line has its name, price, quantity and a picture URL or null", all({"product_name", "unit_price", "quantity", "image", "product_slug"} <= set(i) for i in detail.get("items", [])), detail.get("items"))
        status, body, _ = api.call("GET", "/orders/{number}/", token=access, number=guest_order.number)
        ok("a guest order is a 404 for a customer (never leaks)", status == 404, body)
        stock_before = ProductVariant.objects.get(pk=second["variant_id"]).stock_quantity
        api.call("POST", "/accounts/cart/", token=access, body=line(second, 1, "increase"))
        status, body, _ = api.call("POST", "/orders/", token=access, body=checkout_body([(second, 1)], phone=phone))
        spare = Order.objects.get(number=body["data"]["order_id"])
        order_ids.append(spare.pk)
        ok("a second order takes one unit", ProductVariant.objects.get(pk=second["variant_id"]).stock_quantity == stock_before - 1)
        status, body, _ = api.call("POST", "/orders/{number}/cancel/", token=access, number=spare.number)
        ok("POST /orders/{number}/cancel/ -> cancelled, and the unit is back on the shelf",
           status == 200 and body["data"]["status"] == "cancelled" and body["data"]["payment"]["status"] == "cancelled"
           and ProductVariant.objects.get(pk=second["variant_id"]).stock_quantity == stock_before, body)
        status, body, _ = api.call("POST", "/orders/{number}/cancel/", token=access, number=spare.number)
        ok("cancelling again -> 400", status == 400 and "pending" in body["error"], body)

        # a cash-on-delivery order the courier could not deliver: confirmed (phone call) -> shipped -> returned
        status, body, _ = api.call("POST", "/orders/", token=access, body=checkout_body([(second, 1)], phone=phone))
        failed = Order.objects.get(number=body["data"]["order_id"])
        order_ids.append(failed.pk)
        order_services.change_status(failed, Order.Status.CONFIRMED)
        status, body, _ = api.call("GET", "/orders/{number}/", token=access, number=failed.number)
        ok("a confirmed order reads Confirmed and the customer can no longer cancel it",
           status == 200 and body["data"]["status_display"] == "Confirmed" and body["data"]["can_cancel"] is False, body)
        status, body, _ = api.call("POST", "/orders/{number}/cancel/", token=access, number=failed.number)
        ok("cancelling a confirmed order -> 400 (a person decides)", status == 400, body)
        order_services.change_status(failed, Order.Status.SHIPPED)
        order_services.change_status(failed, Order.Status.RETURNED)
        status, body, _ = api.call("GET", "/orders/{number}/", token=access, number=failed.number)
        ok("a returned parcel: status Returned, payment cancelled, history pending -> confirmed -> shipped -> returned, goods back",
           status == 200 and body["data"]["status"] == "returned" and body["data"]["payment"]["status"] == "cancelled"
           and [h["status"] for h in body["data"]["history"]] == ["pending", "confirmed", "shipped", "returned"]
           and ProductVariant.objects.get(pk=second["variant_id"]).stock_quantity == stock_before, body)

        phase("Delivery (staff) and a review with a photo and a video")
        order_services.change_status(order, Order.Status.SHIPPED)
        order_services.change_status(order, Order.Status.DELIVERED)
        ok("delivered: the cash was collected (payment paid)", list(order.payments.values_list("status", flat=True)) == ["paid"])
        status, body, _ = api.call("GET", "/orders/{number}/", token=access, number=order.number)
        ok("the order now reads delivered and paid, history pending -> shipped -> delivered, no longer cancellable",
           status == 200 and body["data"]["status"] == "delivered" and body["data"]["payment"]["status"] == "paid" and body["data"]["can_cancel"] is False
           and [h["status"] for h in body["data"]["history"]] == ["pending", "shipped", "delivered"], body)
        status, body, _ = api.call("POST", "/orders/{number}/cancel/", token=access, number=order.number)
        ok("a delivered order can not be cancelled -> 400", status == 400, body)
        status, body, _ = api.call("GET", "products/reviews/", token=access, query=f"product_id={first['id']}")
        ok("can_review is true after delivery", status == 200 and body["data"]["can_review"] is True and body["data"]["review_status"] == "can_review" and body["data"]["order_id"] is None, body)
        status, body, _ = api.call("POST", "products/reviews/", token=access, fields=[("product_id", first["id"]), ("rating", 4), ("comment", "Good product.")],
                                   files=[("media", "photo.png", "image/png", png()), ("media", "clip.mp4", "video/mp4", MP4)])
        review = body.get("data") or {}
        ok("POST products/reviews/ (multipart, repeated media) -> 201 with the Review shape", status == 201 and {"id", "product_id", "user_name", "rating", "comment", "created_at", "can_edited", "media_urls"} == set(review), body)
        if review.get("media_urls"):
            status, content, headers = api.fetch(review["media_urls"][0]["file"])
            ok("the review photo is served, and media_urls[].type is a MIME type", status == 200 and review["media_urls"][0]["type"] == "image/png" and review["media_urls"][1]["type"] == "video/mp4", review["media_urls"])
        status, body, _ = api.call("POST", "products/reviews/", token=access, fields=[("product_id", first["id"]), ("rating", 1), ("comment", "again")])
        ok("a second review of the same product -> 400", status == 400, body)
        status, body, _ = api.call("GET", "products/reviews/", token=access, query=f"product_id={first['id']}")
        ok("after reviewing: review_status is reviewed", status == 200 and body["data"]["review_status"] == "reviewed", body)
        status, body, _ = api.call("POST", "products/reviews/", token=access, fields=[("product_id", second["id"]), ("rating", 5), ("comment", "Nice")])
        ok("... and one of a product of the same order works (it was delivered too)", status == 201, body)
        status, body, _ = api.call("PUT", "products/reviews/{id}/", token=access, id=review.get("id", 0),
                                   fields=[("product_id", first["id"]), ("rating", 2), ("comment", "Changed my mind."), ("media", "[object Object]"), ("media", "[object Object]")])
        ok("PUT products/reviews/{id}/ as the frontend sends it ('[object Object]' media) -> 200, media kept",
           status == 200 and body["data"]["rating"] == 2 and len(body["data"]["media_urls"]) == 2, body)
        status, body, _ = api.call("PUT", "products/reviews/{id}/", token=access, id=review.get("id", 0), fields=[("rating", 2)], files=[("media", "x.png", "image/heic", HEIC)])
        ok("a HEIC photo is refused -> 400", status == 400, body)
        status, body, _ = api.call("GET", "products/reviews/", query=f"product_id={first['id']}")
        ok("a guest sees the review, not editable, and can not review", status == 200 and body["data"]["count"] == 1 and body["data"]["results"][0]["can_edited"] is False and body["data"]["can_review"] is False, body)
        status, body, _ = api.call("GET", "/products/detail/{slug}", slug=first["slug"])
        # The rating is recounted from the real reviews, so it replaces the made-up numbers `seed_catalog` puts on products.
        ok("the product's rating is recounted from its real reviews (1 review, rating 2 after the edit)",
           status == 200 and body["data"]["total_reviews"] == 1 and body["data"]["avg_rating"] == 2, {k: body["data"].get(k) for k in ("total_reviews", "avg_rating")})

        phase("Tokens: refresh (with an old access token in the header), revoke")
        status, body, _ = api.call("POST", "accounts/token/refresh/", token=access, body={"expiresInMins": 1, "refresh": refresh})
        new = body.get("data") or {}
        ok("POST accounts/token/refresh/ -> a new access AND a new refresh", status == 200 and new.get("access") and new.get("refresh") and new["refresh"] != refresh, body)
        status, body, _ = api.call("POST", "accounts/token/refresh/", body={"refresh": refresh})
        ok("the old refresh token is dead -> 401", status == 401, body)
        status, body, _ = api.call("POST", "accounts/logout/", token=new.get("access"), body={"access": new.get("access"), "refresh": new.get("refresh")})
        ok("POST accounts/logout/ -> 200", status == 200, body)
        status, body, _ = api.call("POST", "accounts/token/refresh/", body={"refresh": new.get("refresh")})
        ok("a logged-out refresh token -> 401", status == 401, body)
        status, body, _ = api.call("GET", "/products", token="not-a-token", query="page=1&page_size=1")
        ok("a bad token on a public endpoint -> 401 (so the frontend refreshes it)", status == 401, body)
        status, body, _ = api.call("GET", "/accounts/profile/")
        ok("a protected endpoint without a token -> 401", status == 401, body)

    finally:
        phase("Clean up")
        if user is not None:
            user.refresh_from_db()
            if user.profile_picture:
                user.profile_picture.delete(save=False)
        Review.objects.filter(user=user).delete() if user is not None else None
        for order in Order.objects.filter(pk__in=order_ids):
            order.payments.all().delete()
            order.delete()
        User.objects.filter(phone_number=phone).delete()
        for pk, before in saved.items():
            ProductVariant.objects.filter(pk=before["variant"]).update(stock_quantity=before["stock"])
            Product.objects.filter(pk=pk).update(total_orders=before["orders"], total_reviews=before["reviews"], avg_rating=before["rating"])
        restored = all(
            (ProductVariant.objects.get(pk=b["variant"]).stock_quantity, Product.objects.get(pk=pk).total_orders, Product.objects.get(pk=pk).total_reviews,
             Product.objects.get(pk=pk).avg_rating) == (b["stock"], b["orders"], b["reviews"], b["rating"]) for pk, b in saved.items()
        )
        leftovers = set(glob.glob(str(settings.MEDIA_ROOT / "**" / "*"), recursive=True)) - media_before
        leftovers = {path for path in leftovers if os.path.isfile(path)}
        ok("stock and counters are back, and no smoke customer, order, review or file is left",
           restored and not User.objects.filter(phone_number=phone).exists() and not Order.objects.filter(pk__in=order_ids).exists() and not leftovers,
           f"restored={restored}, files left={sorted(leftovers)}")

    phase("Result")
    ok(f"every response had the envelope and the CORS header ({calls_made} calls)", not problems, "; ".join(problems[:5]))
    missing = [call for call in FRONTEND_CALLS if call not in covered]
    ok(f"every call of the frontend was made ({len(FRONTEND_CALLS) - len(missing)}/{len(FRONTEND_CALLS)})", not missing, missing)
    failed = [label for label, passed in checks if not passed]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed" + (f"; FAILED: {failed}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
