# GoCart API Contract (v0.1)

Canonical contract between the React frontend (`../ecom`) and this backend. It mirrors what `ecom/src` actually
sends and reads today. **Anything that would require a frontend change is marked "proposed" and needs the
user's approval first.**

Every endpoint below is implemented. `config/frontend_calls.py` lists each call the frontend makes (as it spells it);
`config/tests` check that every one of them reaches a view and is in `openapi.yaml`, and `scripts/e2e_smoke.py` replays
them against a running server.

- **Base URL:** `{API_ROOT}/` = `http://localhost:8000/api/v1/`. The frontend's `VITE_BASE_URL` must **end with `/`**.
- **Slashes:** every route answers both with and without a trailing slash, with no redirect. The slash form is canonical.
- **Auth:** `Authorization: Bearer <access>`. JSON unless stated (`multipart/form-data` for uploads).
- **Numbers:** money and ratings are JSON numbers (stored as Decimal, never float). See CLAUDE.md.
- **Phone numbers:** `+880` followed by 10 digits, e.g. `+8801712345678`, in every request and response.

## 1. Envelope, errors, pagination

```jsonc
// success
{ "success": true, "message": "OK", "data": { } }            // data may be an object, an array or null

// paginated list: data is an object; the frontend reads data.results
{ "success": true, "message": "OK",
  "data": { "count": 120, "next": "…?page=3", "previous": "…?page=1", "results": [ ] } }

// every non-2xx
{ "success": false,
  "message": "Validation failed.",                     // short summary
  "error": "Phone number: This field is required.",    // string: the first error
  "errors": ["Phone number: This field is required."], // string[]: what <ErrorDisplay/> renders
  "field_errors": { "phone_number": ["This field is required."] } }   // extra, optional
```

| Status | Meaning |
|---|---|
| 200 / 201 | success (deletes also answer 200 with `data: null`; **no 204**, so the envelope is always present) |
| 400 | validation error, wrong/expired OTP, out of stock, bad state |
| 401 | **only** a missing/expired/invalid access or refresh token (the frontend then refreshes, then logs out) |
| 403 | authenticated but not allowed |
| 404 | unknown route/resource (also `?page=abc`) |
| 413 | the request is too big: an upload over `MAX_UPLOAD_REQUEST_MB` (default 255: 5 review videos of 50 MB plus the text) or a JSON/form body over `DATA_UPLOAD_MAX_MEMORY_SIZE` (2.5 MB). The usual envelope; refused before it is read |
| 429 | throttled (`Retry-After` header) |
| 5xx | server error (body never leaks internals) |

Throttling: every endpoint has a generous default limit (`THROTTLE_ANON` 600/minute per client IP for guests,
`THROTTLE_USER` 1200/minute per signed-in customer; a shop page makes about 10 calls). The endpoints that send an SMS or
take stock (auth, orders, reviews, profile OTP) have tighter scopes of their own, listed with them below; a test fails
if a new public write endpoint has none. The client IP is the address the reverse proxy appended to
`X-Forwarded-For` (`NUM_PROXIES`), never the header as the client wrote it.

Pagination: `?page=` (1-based) and `?page_size=` (default 30, max 120; the UI offers 30/60/90/120).
A page past the end returns 200 with `results: []` and `next: null`.

## 2. Auth: `/accounts/…` (phone + OTP, no passwords)  *(live)*

| Endpoint | Body | `data` |
|---|---|---|
| `POST /accounts/register/` | `{name, phone_number, email?}` | `{token}`, message `OTP sent to +88017****5678.` Creates an unverified user (or re-uses one that never verified); `400` if the phone is already verified or the email is taken. `token` is an opaque **URL-safe** string (the frontend puts it in the path `/verify-otp/:token`). |
| `POST /accounts/login/` | `{phone_number, expiresInMins?}` (extra key ignored) | `{token}`. `400` if the number is unknown, not verified yet, or the account is disabled. |
| `POST /accounts/verify-otp/` | `{token, otp, cart:[{product_id, quantity, variant_id?}], favorite:[{product_id}]}` (**key is `favorite`**) | `{tokens:{access, refresh}}`. Marks the phone verified. `cart`/`favorite` are optional lists of objects (max 100 each) handed to the shop apps through the `guest_data_received` signal; malformed entries are the receivers' problem and never block sign-in. |
| `POST /accounts/resend-otp/` | `{token}` | `null` (+ message). Same token, new code; also allowed after the old code expired. |
| `POST /accounts/token/refresh/` | `{refresh, expiresInMins?}`; the `Authorization` header (a stale access token) is ignored | `{access, refresh}`. **Always returns a new `refresh`** (rotation); the old one is blacklisted, replaying it is `401`. Invalid/expired/blacklisted refresh, or a disabled/deleted user: `401` (with `WWW-Authenticate: Bearer`). |
| `POST /accounts/logout/` | `{access?, refresh?}` (Bearer ignored) | `null`. Blacklists the refresh token. Idempotent: `200` even if it is missing, invalid or already revoked. `access` is accepted and ignored (access tokens are short-lived and stateless). |

OTP rules (all configurable in `.env`): 6 digits, hashed at rest, valid 5 minutes, max 5 wrong attempts per code, a resend
every 60 s at most and max 3 resends per token, max 5 codes per phone per hour, plus per-IP throttles.
Only the newest code for a number is valid. A wrong/expired/used code is **400** (never 401), with a readable message,
e.g. `Invalid OTP. 4 attempts left.`, `This OTP has expired. Please request a new one.`,
`Too many incorrect attempts. Please request a new OTP.` Throttled requests are `429` with `Retry-After`.
A delivery failure is `503` (nothing is created). In dev the code is printed in the server log.

**Dev only, never production:** with `OTP_BACKEND=apps.accounts.otp.backends.BrowserOTPBackend` the `message` of
`register/`, `login/`, `resend-otp/` and `request-otp/` also carries the code, e.g.
`OTP sent to +88017****5678. [DEV] Your code is 123456.` (or `A new OTP has been sent. [DEV] Your code is 123456.`),
so the frontend shows it without any change. `data` and every other message stay as documented. That backend refuses to
work unless `DEBUG=True` (the request then fails with `503`) and the prod settings refuse to start with it: a production
response never contains a code. Clients must not parse or rely on this text.

## 3. Profile & addresses (auth required)  *(live)*

| Endpoint | Request | `data` |
|---|---|---|
| `GET /accounts/profile/` | | `{name, username, email, phone_number, date_of_birth, gender, profile_picture}`: `phone_number` never null; `username`/`email`/`date_of_birth`/`profile_picture` are `null` when unset; `gender` ∈ male/female/other/`""`; `profile_picture` is an absolute URL |
| `PUT /accounts/profile/` (`PATCH` is an alias) | multipart or JSON, **partial**: send only what changed (or just `profile_picture`). Unknown/privileged keys (`is_staff`, `id`, …) are ignored | the updated profile |
| `POST /accounts/request-otp/` | `{phone_number}` **or** `{email}` (exactly one): the NEW value | `{token}`, message `OTP sent to +88017****5678.` `400` if it is the user's current value or belongs to another account |
| `POST /accounts/verify-otp-for-profile/` | `{token, otp}` | `{field: "phone_number"\|"email", value}`. Wrong OTP = **400** (never 401). The token must belong to the caller |
| `GET /accounts/addresses/` | | **plain array** of Address (not paginated), oldest first |
| `POST /accounts/addresses/` | Address fields (`201`) | the created Address incl. `id` |
| `GET /accounts/addresses/{id}/` | | one Address |
| `PUT /accounts/addresses/{id}/` (`PATCH` alias) | the whole edited Address or just some fields (**partial**); `id` and other read-only keys are ignored | the updated Address |
| `DELETE /accounts/addresses/{id}/` | | `null` (200) |

**Changing the phone number or email.** A new `phone_number`/`email` in `PUT /profile/` is accepted only if that exact
value was verified with `request-otp/` + `verify-otp-for-profile/` within the last 15 minutes
(`PROFILE_VERIFICATION_WINDOW_SECONDS`), and one verification pays for one change; otherwise `400` with
`field_errors.<field> = ["Verify this … with an OTP before saving it."]`. Re-saving the current value needs no OTP,
and `email: ""` removes the email without one. A verified new phone number replaces the login number at once.

**Validation:** `name` ≤ 150 chars, not blank; `username` 3-50 chars of `A-Za-z0-9_.-`, unique ignoring case (`""` clears it);
`date_of_birth` `YYYY-MM-DD`, not in the future, ≥ 1900; `gender` male/female/other/`""`.
In a *multipart* form an empty field means "not sent" (DRF's rule), in JSON `""` is a real value.

**Profile picture:** JPEG, PNG or WebP (real format is checked, not the file name), ≤ 5 MB (`MAX_IMAGE_UPLOAD_MB`);
stored under a random name (the original filename is discarded); the previous picture file is deleted when replaced.

`Address = {id, title, shipping_type: "inside_dhaka"|"outside_dhaka", address, area, division, district, thana}`.
Location values are plain names (from the frontend's static `location.js`). `shipping_type` and `address` are required;
`inside_dhaka` requires `area`, `outside_dhaka` requires `division`, `district`, `thana`; fields that do not apply are
cleared. `title` is optional. At most 20 addresses per user (`MAX_ADDRESSES_PER_USER`). Someone else's address is a `404`.

## 4. Cart & wishlist (auth required)  *(live)*

`variant_id` missing and the product has exactly one (default) variant → that variant; several variants → 400.

| Endpoint | Request | Response |
|---|---|---|
| `GET /accounts/cart/` | | `data`: array of flattened cart items = product-list fields (§5) + `quantity, color_name, color_hex_code, size_name, variant_id, image`. **`id` is the product id.** |
| `POST /accounts/cart/` | `{product_id, quantity, variant_id?, action:"increase"\|"decrease"}`; **`quantity` is a delta** | `{success:true}`; decreasing to ≤ 0 removes the line |
| `PUT /accounts/cart/` (= remove) | an object `{product_id, variant_id?}` **or** an array of them (Cart "clear all"; Checkout sends `{product_id}` without `variant_id`) | `{success:true}`; no `variant_id` → all lines of that product |
| `GET /accounts/favourite/` | | array of product-list items |
| `POST /accounts/favourite/` | `{product_id}` | `{success:true}` (idempotent) |
| `PUT /accounts/favourite/` (= remove) | `{product_id}` or `[{product_id}]` | `{success:true}` |

**How the cart and the wishlist behave**

- A cart line is a **variant** (one per user and variant). A product with several variants and no `variant_id` is a 400
  ("Choose a colour or size first."); a variant that is not the product's, is inactive, or a product that is hidden or
  has no variants is a 400 ("... is not available."). `variant_id: null` counts as missing.
- `POST` adds a **delta** (`quantity` defaults to 1, `action` to `increase`). Asking for more than the stock is a
  **400** ("Only 3 of Mug left in stock (you already have 2 in your cart).", "Mug is out of stock.") and changes
  nothing; nothing is reserved, stock is taken when the order is placed. `decrease` takes it off; 0 or less deletes the
  line; a line that is not there is a harmless no-op. The number of lines is limited (`MAX_CART_LINES`, default 50).
- The **minimum order quantity is not checked in the cart** (the frontend cart does not enforce it either): it is
  checked when the order is placed.
- `PUT` removes: one `{product_id, variant_id?}` or an array of them (at most 200); without `variant_id` every line of
  that product goes; what is not in the cart is ignored. Both answer `{success: true, data: null}`.
- `GET /accounts/cart/` is a plain array (not paginated), oldest line first; growing a line does not move it. Each entry is a product card (section 5)
  with the **chosen variant's** `base_price` / `discount_price` / `has_discount` / `variant_id` / `availability_status`,
  the chosen colour's picture as `image` (else the main one) and `quantity`, `color_name`, `color_hex_code`,
  `size_name` (null when the variant has none). `id` is the **product** id; a product with two variants in the cart
  appears twice. Lines whose product or variant is hidden are left out (and come back when it is visible again).
- `GET /accounts/favourite/` is a plain array of product cards, newest favourite first, each with `is_favourite: true`;
  hidden products are left out. `POST` is idempotent; `PUT` takes one `{product_id}` or an array (at most 500) and
  ignores what was never saved. At most `MAX_FAVOURITES_PER_USER` (default 200); saving a product that is already
  saved never counts against it.
- **Guest merge at sign-in**: `POST /accounts/verify-otp/` may carry the guest's `cart: [{product_id, quantity,
  variant_id?}]` and `favorite: [{product_id}]` (sic). They are added to the account's own; the merge never fails a
  sign-in: an unusable entry is skipped (not a dict, bad numbers, unknown or hidden product, a variant of another
  product, several variants and none named), the same variant twice is added up, the total is **capped at the stock**
  (an out-of-stock variant is skipped), the line and favourite limits are respected, and only the first 200 / 500
  entries are read.

## 5. Catalog & content (public; a Bearer token is optional: it personalises `is_favourite` and `/content/checkout`)  *(live)*

`GET /products/` query: `page, page_size, ordering, category (slug, includes child categories), brands, tags, colors,
sizes (comma separated names), min_price, max_price (effective price), discount_type + discount_value (exact match),
search`. `ordering` ∈ `price, -price, discount_price, -discount_price, rating, -rating` (empty = newest first).
`/products/new-arrivals/`, `/products/best-selling/`, `/products/flash-sale/`, `/products/featured/` take `page, page_size`.

**Product list item:** `id, name, slug, sku, image, base_price, discount_price, has_discount, discount_type
("percentage"|"fixed"), discount_value, brand_name, total_views, total_orders, total_reviews, avg_rating (number),
availability_status (bool), has_variants (bool), variant_id, minimum_order_quantity, is_favourite`.
`discount_price` is always a number (equals `base_price` when there is no discount). `minimum_order_quantity` is the
product's smallest order (1 unless the shop set more): an order below it is refused (section 6), so a cart line (which
is a card too) can warn early.

**`GET /products/detail/{slug}/`** = list item plus: `brand{name}, categories[{name,slug}], category (primary slug),
tags[{name}], thumbnail, media_files[{file_type:"image"|"video", file_url, thumbnail_url}], minimum_order_quantity,
short_description, long_description (sanitized HTML), model, weight, dimension{width,height,depth}, material, features,
warranty_information, shipping_information, return_policy, qrcode_image_url` and variants:

- colors: `colors:[{name, hex_code, variant_id?, base_price?, discount_price?, media_files[], sizes:[{name, variant_id, base_price, discount_price, availability_status}]}]`
- no colors: `sizes:[{name, variant_id, base_price, discount_price, availability_status}]`
- Increments `total_views`.

| Endpoint | `data` |
|---|---|
| `GET /products/search-suggestions/?q=` | `["name", …]` (≤ 10 strings) |
| `GET /products/categories/` and `…/flash-sale/`, `…/new-arrival/`, `…/best-selling/`, `…/feature/` | paginated `{id, name, slug, image, has_discount, discount_amount, discount_type}` |
| `GET /content/pages/{home,newarrival,flashsale,best_selling,feature,category}/` | `{page_content:{image_sliders[], video_sliders[], left_banner, right_banner}}` |
| `GET /content/shop/` | `{categories:[{name,slug,children[]}], brands:[name], tags:[name], colors:[{name,hex_code}], sizes:[name], price_range:{min_range,max_range}, discounts:[{discount_type,value}]}` |
| `GET /content/checkout/` | `{delivery_charges:{inside_dhaka, outside_dhaka}` (numbers)`, shipping_addresses:[Address]` (guest: `[]`)`, user_info:{name,phone_number,email}` (guest: `null`)`}` |

**How the catalog behaves**

- Only active products (and active categories) are visible; anything else is a 404 on the detail page and absent from
  every list.
- **Prices on a card and in filters are those of the variant the card adds to the cart**: the default active variant
  (`is_default`, else the lowest id), with its own `base_price` / `discount_price` when it overrides the product's, else
  the product's discount rule. A product without variants uses its own price. `variant_id` is that variant.
  `has_variants` is true only when a colour or size has to be chosen (then the card opens the detail page).
- `min_price` / `max_price` (inclusive) compare with what the customer pays (`discount_price`). `ordering=price` sorts by
  `base_price` (before the discount), `discount_price` by what the customer pays, `rating` by `avg_rating`. Equal values
  fall back to newest first, so pages never repeat a product.
- Filters: different parameters narrow the result (AND), several comma separated values of one parameter widen it (OR,
  case-insensitive). `colors` + `sizes` must match the **same** variant. `discount_type` + `discount_value` are an exact
  match of the product's discount (the pairs offered by `/content/shop`). `search`: every word must appear in the name,
  SKU, model, brand name or a tag. Blank values (`?min_price=`) and unknown keys are ignored; a malformed value
  (`ordering=x`, `min_price=abc`) is a 400 with `field_errors`.
- `/products/new-arrivals|best-selling|flash-sale|featured` list the products the admin flagged (best selling: most
  orders first, the others newest first) and take only `page`, `page_size`.
- A page past the end is an empty `results` list, not a 404.
- **Detail** `colors` / `sizes` are **left out** (not `[]`) when they do not apply: the frontend tests `!product.colors`.
  Colours come with the default variant's colour first, sizes in size order. A colour sold without sizes has `sizes: []`
  and carries its own `variant_id`, `base_price`, `discount_price`, `availability_status`. Only active variants are
  offered. `media_files` is the shared gallery when the product has colours (each colour has its own, falling back to the
  shared one) and every file otherwise. `thumbnail` is the main image's thumbnail (the first shared image, then the admin's
  order); `image` in the list is that same image. A video's `thumbnail_url` is null unless a poster was uploaded.
  `dimension` is null when no measure is set; `discount_type` is null when there is no discount.
- Every successful detail request adds one to `total_views`; the response already shows the new value.
- `is_favourite` is true for the signed-in customer's favourites (section 4) and false for guests; the wishlist app
  registers a provider with the catalog, one lookup per page.
- `/content/shop`: only categories, brands, tags, colours and sizes that a visible product really has;
  `price_range` is the lowest and highest price customers pay; `discounts` are the distinct (type, value) pairs.
- `/content/pages/{page}/` (`home, newarrival, flashsale, best_selling, feature, category`; any other page is a 404).
  Answers `{page_content: {image_sliders[], video_sliders[], left_banner, right_banner}}`; a page nobody filled in yet
  gives empty lists and null banners, never an error. Each item has `type` (`product` | `category` | `external`),
  `link` (the product or category **slug**, null for `external`), `external_link` (null unless `external`), `media`
  (absolute URL), `media_type` and `caption` (`""` when empty). `order` is **1, 2, 3...** in the order the admin
  arranged the items, not the stored number, because the frontend uses it as the React key of a slide.
  An item is visible while it is active and its product or category is visible. A page has at most one active
  left banner and one active right banner. Slider and left banner take an image, the video slider a video, the
  right banner either. `external_link` is always `http(s)://`.
- `/products/categories…` list every active category A-Z (flat, with images), the flagged variants only the flagged ones.
- **`/content/checkout/`** (public; the Bearer token is optional, an expired one is a 401 like everywhere else):
  - `delivery_charges` are what an order will be charged, as JSON **numbers** (the frontend calls `.toFixed(2)` on
    them): `inside_dhaka` 60 and `outside_dhaka` 120 by default, edited by staff in the admin (Orders > Delivery
    charges). A shipping type without a configured charge is left out of the object (an order with it is a 400).
    The frontend treats a charge of `0` as "not set" and blocks the form, so free delivery needs a frontend change.
  - `shipping_addresses` is the signed-in customer's saved addresses (section 3), oldest first; `[]` for a guest.
  - `user_info` is `{name, phone_number, email}` of the signed-in customer (`phone_number` is always a string,
    `email` is `""` when there is none), `null` for a guest. The frontend uses it to pre-fill the form.

CMS item (slider/banner): `{order, type:"product"|"category"|"external", link, external_link, media, media_type:"image"|"video", caption}`.
All media URLs are absolute.

## 6. Orders  *(live)*

`POST /orders/` (guest or authenticated):

```jsonc
{ "name": "…", "email": "", "phone_number": "+8801712345678",
  "shipping_type": "inside_dhaka", "shipping_area": "Gulshan", "shipping": null,
  "shipping_division": "", "shipping_district": "", "shipping_thana": "", "shipping_address": "…",
  "payment_type": "cash",                       // "cash" and "cod" both mean Cash on Delivery
  "items": [{ "product_id": 1, "variant_id": 3, "quantity": 2, "price": 500 }],
  "sub_total_price": "1000.00", "delivery_charge": 60, "total_price": "1060.00" }
```

`201 → {success: true, message: "Order placed.", data: {order_id, status, created_at, subtotal, delivery_charge, total}}`;
`order_id` is the human-readable, URL-safe order number, e.g. `GC-20260923-0001` (the frontend navigates to
`/order-confirmation/{order_id}`), and the rest is what that page can show without another call (a guest has no way to
read the order afterwards except by tracking it, see below).

**Who can order.** Guests (no token) and signed-in customers. A valid Bearer token attaches the order to that account;
an expired or invalid token is a `401` (the frontend refreshes it), never a silent guest order. A guest order is
never linked to an account afterwards, not even to one with the same phone number. Ordering is rate limited (scope
`order`, `THROTTLE_ORDER`, default `30/hour`): per client IP for guests, per account for signed-in customers, failed
attempts count too; over the limit is `429` with `Retry-After`.

**Body rules.** `name` ≤ 150 chars, required. `email` optional (`""` and `null` are fine). `phone_number` is `+880` and 10
digits. `shipping_type` is `inside_dhaka` (needs `shipping_area`) or `outside_dhaka` (needs `shipping_division`,
`shipping_district`, `shipping_thana`); fields that do not apply are cleared, like in a saved address (section 3).
`shipping_address` required, ≤ 500. `payment_type` is `cash` or `cod` (both = cash on delivery; default `cash`).
`items` has 1 to `MAX_CART_LINES` (50) entries `{product_id, variant_id?, quantity}` with `quantity` 1 to 10000; a
missing or `null` `variant_id` means the product's only active variant (several variants and none named is an error).
Any other key (`price`, `sub_total_price`, `delivery_charge`, `total_price`, `shipping`, …) is ignored.

**The server prices everything.** Prices and totals sent by the client are ignored; a mismatch is not an error.
Each line costs the variant's final price (the variant's own price when it overrides the product's, else the product's
discount rule, see section 5); `subtotal` is the sum of the lines, `delivery_charge` comes from the configured charge of
the shipping type (default 60 inside Dhaka, 120 outside), `total = subtotal + delivery_charge`. Everything is stored as
a snapshot (contact, address, product name, variant label, SKU, unit and base price, delivery charge), so later
edits to the catalog, the charges or the profile never change a placed order.

**Errors.** A `400` for: an empty or too long `items` list, a bad field, an unknown, hidden or variant-less product, a
variant that is not the product's or is inactive, several variants and none chosen, out of stock, more than the stock,
`quantity` below the product's `minimum_order_quantity`, or a shipping type with no configured delivery charge. All
the problems of an order are reported **together**, one plain sentence each, and nothing is written:

```jsonc
{ "success": false, "message": "Validation failed.", "error": "Mug is out of stock.",
  "errors": ["Mug is out of stock.", "Only 3 of Cap left in stock.", "The minimum order for Pen is 4.",
             "Delivery is not available for this shipping type right now."] }
```

Field problems (bad phone, missing area, …) come first, on their own, with `field_errors`; the stock, minimum and
availability checks only run once the request itself is well formed. The same variant listed twice is added up first,
and the minimum order quantity is checked per (merged) variant line. A hidden product is reported by id, never by name.
The checks and the stock are read under a row lock, so two customers racing for the last unit get one `201` and one
`400` ("… is out of stock."), never an oversell.

**What a successful order does.** Status `pending` (one `OrderStatusHistory` row), the ordered quantities leave the
stock, each distinct product's `total_orders` ("N orders" on the shop) goes up by one (per order, not per unit), and
for a signed-in customer the ordered variants leave their server cart (the other lines stay).

**Order number.** `<prefix>-YYYYMMDD-NNNN`: `ORDER_NUMBER_PREFIX` (default `GC`), the date in the shop's time zone
(Asia/Dhaka), and a counter that restarts at `0001` every day (zero padded to 4 digits, it simply grows longer after
9999). A failed order does not use up a number.

**Statuses:** `pending, confirmed, paid, shipped, delivered, returned, cancelled, refunded` (the frontend was built on
the six without `confirmed` and `returned`; nothing was renamed). Only staff change them (Django admin: the status
field and the bulk actions "Mark as confirmed / paid / shipped / delivered / returned", "Cancel and restock"); every
change writes an `OrderStatusHistory` row. The allowed moves are defined once, in `apps/orders/state.py`:

| from | may become |
|---|---|
| `pending` | `confirmed`, `paid`, `shipped`, `cancelled` |
| `confirmed` | `paid`, `shipped`, `cancelled` |
| `paid` | `shipped`, `cancelled`, `refunded` |
| `shipped` | `delivered`, `returned`, `cancelled` |
| `delivered` | `refunded` |
| `cancelled`, `returned`, `refunded` | nothing (final) |

`confirmed` (staff checked the order, e.g. by phone) and `paid` are **optional** steps: a cash-on-delivery order
normally goes `pending -> shipped -> delivered` (the cash is collected at the door, so the payment turns paid then), a
shop that phones its customers adds `confirmed`, a prepaid order goes through `paid`. `delivered` and `returned` are
only reachable from `shipped`. `returned` = the shipped parcel came back (delivery failed, or the customer refused
it).

The goods go back into stock (and `total_orders` of each distinct product goes down by one, never below 0) when an
order is **cancelled** (from `pending`, `confirmed`, `paid` or `shipped`), when a shipped parcel is **returned**, or
when a **`paid` order is refunded**. A **`delivered` order that is refunded is not restocked**: the goods already
left, and whether they come back sellable is for a person to decide (edit the stock in the admin; returned goods that
are damaged are corrected the same way). Every one of these statuses is final or moves on only once, so goods are
never returned twice. A customer can still cancel only a **pending** order (once staff confirm it, a person decides).

**Payments** (no endpoint: the frontend offers cash on delivery only, so nothing is exposed to it). Every order gets one
`Payment` row in the same transaction that places it (`pending`, amount = the order total, method `cod`), and the
payment follows the order's status through the orders app's signals, also inside one transaction: a failure on either
side rolls both back.

| The order becomes | A `pending` payment becomes | A `paid` payment becomes |
|---|---|---|
| `confirmed` | (unchanged) | (unchanged) |
| `paid` (staff marked it) | `paid` | (unchanged) |
| `shipped` | (unchanged: nothing is collected yet) | (unchanged) |
| `delivered` (the courier collected the cash) | `paid` | (unchanged) |
| `returned` (the parcel came back) | `cancelled` | `refunded` |
| `cancelled` | `cancelled` | `refunded` |
| `refunded` | `cancelled` | `refunded` |

Payment statuses: `pending -> paid | cancelled`, `paid -> refunded`; `cancelled` and `refunded` are final. `paid_at` and
`refunded_at` are stamped once. The staff see the ledger (read-only) under **Payments** in the Django admin; they move
the ORDER and the payment follows. A refund only records that the shop gave the money back; it does not move money.
Orders placed before the payments app existed get their payment from a data migration. A gateway later is a new
`PaymentProvider` in `apps/payments/providers.py`.

### Reading and cancelling orders (signed in), and tracking (guests)

`{order_id}` is the order number (`GC-20260923-0001`). All of these answer in the usual envelope.

- `GET /orders/` → `data: {count, next, previous, results: [Order summary]}`. The signed-in customer's **own** orders,
  newest first, paginated like the product lists (`?page=&page_size=`). A guest order belongs to nobody, so it is in no
  list. Order summary: `{order_id, status, status_display, created_at, total, items_count, items: [Item]}`;
  `items_count` counts units.
- `GET /orders/{order_id}/` → `data: Order` = the summary plus `name, email, phone_number, shipping_type, shipping_area,
  shipping_division, shipping_district, shipping_thana, shipping_address, subtotal, delivery_charge, can_cancel,
  payment, history`. `payment` is `{method, method_display, status, status_display, amount, paid_at, refunded_at}` or
  `null` (the payment of section 6, newest one). `history` is every status the order has been in, oldest first:
  `[{status, status_display, created_at}]` (who moved it and the staff's note are not shown). `can_cancel` is true
  while the order is `pending`. Somebody else's order, a guest order and an unknown number are the same `404`.
- `Item = {product_id, product_slug, product_name, variant_label, sku, unit_price, base_price, quantity, line_total,
  image}`: the snapshot of what was bought and paid; `product_id` and `product_slug` are `null` once the product was
  deleted, `image` is the product's current main image (absolute URL) or `null`.
- `POST /orders/{order_id}/cancel/` (no body) → `200`, `data: Order` (now `cancelled`). Only a **pending** order: the
  goods go back into stock, `total_orders` goes down and the payment is cancelled, all through the same status change
  as the staff's. Any other status is a `400` (`Only a pending order can be cancelled. To change an order that is
  already being handled, please contact us.`); somebody else's order is a `404`. Two clicks at once cancel it once.
  Shares the `order` throttle scope with placing orders.
- `GET /orders/track/?order_id=GC-…&phone_number=+880…` (**public**, no token needed; a stale token is ignored) →
  `data: Order summary` + `subtotal, delivery_charge, payment, history`, and **nothing about who the order is for or
  where it goes** (no name, e-mail, phone or address): an order number is easy to guess, the phone number is the only
  secret. A wrong number and a wrong phone number are the same `404` (`No order matches these details.`), the number
  may be typed in any case, missing or malformed input is a `400`. Throttled per client IP (scope `order_track`,
  `THROTTLE_ORDER_TRACK`, default `30/hour`); wrong guesses count, and past the limit even a right answer waits (`429`).

## 7. Reviews

- `GET /products/reviews/?product_id=` (public; a valid Bearer token fills in `can_review` and `can_edited`; an
  expired one is a 401) → `data:{count, next, previous, results:[Review], can_review, review_status, order_id}`. Newest
  first, paginated like the product lists (`?page=&page_size=`, 30 per page, at most 120; a page past the end is an
  empty `results`). `can_review` = the signed-in customer has a **delivered** order containing the product and has not
  reviewed it yet (always `false` for a guest). `review_status` says where the customer stands, so the shop can tell
  them why (same on every page):

  | `review_status` | Meaning | `order_id` |
  |---|---|---|
  | `can_review` | a delivered order of theirs contains it, not reviewed yet (`can_review` is true) | `null` |
  | `reviewed` | they reviewed it (a review the staff hid counts) | `null` |
  | `waiting_for_delivery` | they ordered it and the order is `pending`, `paid` or `shipped` | the newest such order's number (link to `GET /orders/{order_id}/`) |
  | `not_purchased` | signed in, no order of theirs on its way or delivered contains it (a cancelled or refunded order counts for nothing; so does somebody else's or a guest order) | `null` |
  | `guest` | not signed in | `null` |

  A delivered order wins over a newer one that is still on its way; `reviewed` wins over both. A missing or
  non-numeric `product_id` is a 400, an unknown or hidden product a 404.
- `POST /products/reviews/` (multipart or JSON: `product_id, rating (1-5, whole), comment, media[]`; signed in) → `201`,
  `data` = the created Review. A `400` when the product is not available, when the customer already reviewed it
  (`You have already reviewed this product. Edit your review instead.`), or when no delivered order of theirs contains
  it (`You can review a product once an order that contains it has been delivered.`). The comment is trimmed, must not
  be empty and has at most 2000 characters. The review is shown at once (no approval step).
- `PUT /products/reviews/{id}/` (multipart; signed in) → `200`, `data` = the updated Review. Every field is optional;
  `product_id` may only repeat the review's own. Only the author: someone else's review, a hidden one, or an unknown
  id is a `404`. **New files are added to the review's media** (5 in all, existing ones count); text values under `media`
  (the frontend re-sends the existing media objects as `"[object Object]"`) are ignored, so an edit never removes media.
- `Review = {id, product_id, user_name, rating, comment, created_at, can_edited, media_urls:[{file, type}]}`.
  `user_name` is the author's name (`"Customer"` if empty), never their phone number or e-mail. `can_edited` is true for
  the signed-in author. `media_urls[].file` is an absolute URL whose extension matches the file's real type
  (`jpg|png|webp|mp4|webm`); `type` is its MIME type (`image/jpeg`, `video/mp4`, ...), what `<source type=...>` needs.
- Upload limits (configurable): image ≤ 5 MB (jpeg/png/webp), video ≤ 50 MB (mp4/webm), ≤ 5 files per review. The type is
  read from the file's bytes, not its name. A bad file is a `400` with `field_errors.media = ["<file name>: <reason>"]`
  and nothing is saved.
- Writes are throttled per customer (`THROTTLE_REVIEW`, default 30/hour, writing and editing share it); reading is not.
- The product's `total_reviews` and `avg_rating` (two decimals, half up) count the approved reviews and are updated
  in the same transaction as the review. The staff can hide a review in the Django admin (it then leaves the list and
  the rating, and its author can no longer edit it) or delete it.

## 8. Other

- `GET /health/` → `data: {status:"ok", database:"ok"}`; `503` with the error envelope if PostgreSQL is unreachable. *(live)*
- `GET /api/schema/` (OpenAPI 3) and `GET /api/docs/` (Swagger UI) are served at the site root, outside `/api/v1/`, when `ENABLE_API_DOCS=True`.
