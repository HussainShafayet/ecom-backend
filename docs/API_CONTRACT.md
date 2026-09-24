# GoCart API Contract (v0.1)

Canonical contract between the React frontend (`../ecom`) and this backend. It mirrors what `ecom/src` actually
sends and reads today. **Anything that would require a frontend change is marked "proposed" and needs the
user's approval first.**

Implementation status is tracked in the plan; sections marked *(live)* are implemented (health, auth, profile, addresses so far).

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
| 429 | throttled (`Retry-After` header) |
| 5xx | server error (body never leaks internals) |

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

## 4. Cart & wishlist (auth required)

`variant_id` missing and the product has exactly one (default) variant → that variant; several variants → 400.

| Endpoint | Request | Response |
|---|---|---|
| `GET /accounts/cart/` | | `data`: array of flattened cart items = product-list fields (§5) + `quantity, color_name, color_hex_code, size_name, variant_id, image`. **`id` is the product id.** |
| `POST /accounts/cart/` | `{product_id, quantity, variant_id?, action:"increase"\|"decrease"}`; **`quantity` is a delta** | `{success:true}`; decreasing to ≤ 0 removes the line |
| `PUT /accounts/cart/` (= remove) | an object `{product_id, variant_id?}` **or** an array of them (Cart "clear all"; Checkout sends `{product_id}` without `variant_id`) | `{success:true}`; no `variant_id` → all lines of that product |
| `GET /accounts/favourite/` | | array of product-list items |
| `POST /accounts/favourite/` | `{product_id}` | `{success:true}` (idempotent) |
| `PUT /accounts/favourite/` (= remove) | `{product_id}` or `[{product_id}]` | `{success:true}` |

## 5. Catalog & content (public; a Bearer token is optional and only personalises `is_favourite`)  *(live: `/products/…` and `/content/shop`; `/content/pages/*` and `/content/checkout` are still to come)*

`GET /products/` query: `page, page_size, ordering, category (slug, includes child categories), brands, tags, colors,
sizes (comma separated names), min_price, max_price (effective price), discount_type + discount_value (exact match),
search`. `ordering` ∈ `price, -price, discount_price, -discount_price, rating, -rating` (empty = newest first).
`/products/new-arrivals/`, `/products/best-selling/`, `/products/flash-sale/`, `/products/featured/` take `page, page_size`.

**Product list item:** `id, name, slug, sku, image, base_price, discount_price, has_discount, discount_type
("percentage"|"fixed"), discount_value, brand_name, total_views, total_orders, total_reviews, avg_rating (number),
availability_status (bool), has_variants (bool), variant_id, is_favourite`.
`discount_price` is always a number (equals `base_price` when there is no discount).

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
- `is_favourite` is always false until the wishlist exists (step 7); it is filled by a provider that the wishlist app
  registers, one lookup per page.
- `/content/shop`: only categories, brands, tags, colours and sizes that a visible product really has;
  `price_range` is the lowest and highest price customers pay; `discounts` are the distinct (type, value) pairs.
- `/products/categories…` list every active category A-Z (flat, with images), the flagged variants only the flagged ones.

CMS item (slider/banner): `{order, type:"product"|"category"|"external", link, external_link, media, media_type:"image"|"video", caption}`.
All media URLs are absolute.

## 6. Orders

`POST /orders/` (guest or authenticated):

```jsonc
{ "name": "…", "email": "", "phone_number": "+8801712345678",
  "shipping_type": "inside_dhaka", "shipping_area": "Gulshan", "shipping": null,
  "shipping_division": "", "shipping_district": "", "shipping_thana": "", "shipping_address": "…",
  "payment_type": "cash",                       // "cash" and "cod" both mean Cash on Delivery
  "items": [{ "product_id": 1, "variant_id": 3, "quantity": 2, "price": 500 }],
  "sub_total_price": "1000.00", "delivery_charge": 60, "total_price": "1060.00" }
```

`201 → data: {order_id}` (human-readable, URL-safe, e.g. `GC-20260923-0001`).

- Prices and totals sent by the client are **ignored**; the server recomputes them from the database and the
  configured delivery charge. A mismatch is not an error.
- `inside_dhaka` needs `shipping_area`; `outside_dhaka` needs `shipping_division`, `shipping_district`, `shipping_thana`.
- 400 for an empty cart, an inactive/out-of-stock item, `quantity` below `minimum_order_quantity`, or an invalid shipping combination.
- For an authenticated user the ordered lines are removed from the server cart.
- Statuses: `pending, paid, shipped, delivered, cancelled, refunded`.

**Proposed (needs frontend changes + approval, not part of the frozen contract):** `GET /orders/`,
`GET /orders/{order_id}/`, `POST /orders/{id}/cancel/`.

## 7. Reviews

- `GET /products/reviews/?product_id=` → `data:{results:[Review], can_review}`. `can_review` = the authenticated user has a
  **delivered** order containing the product and has not reviewed it yet.
- `POST /products/reviews/` (multipart: `product_id, rating (1-5), comment, media[]`) → the created Review; 400 if not eligible.
- `PUT /products/reviews/{id}/` (multipart) → owner only. Non-file `media` values (the frontend re-sends existing media
  objects as `"[object Object]"`) are ignored.
- `Review = {id, product_id, user_name, rating, comment, created_at, can_edited, media_urls:[{file, type?}]}`.
- Upload limits (configurable): image ≤ 5 MB (jpeg/png/webp), video ≤ 50 MB (mp4/webm), ≤ 5 files.

## 8. Other

- `GET /health/` → `data: {status:"ok", database:"ok"}`; `503` with the error envelope if PostgreSQL is unreachable. *(live)*
- `GET /api/schema/` (OpenAPI 3) and `GET /api/docs/` (Swagger UI) are served at the site root, outside `/api/v1/`, when `ENABLE_API_DOCS=True`.
