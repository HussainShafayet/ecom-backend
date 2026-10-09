# CLAUDE.md — GoCart Backend

<!-- TEMPLATE: this repo is reused for other projects. Lines tagged [PROJECT] must be rewritten when you start a
new project from it. See docs/NEW_PROJECT.md. -->

[PROJECT] Django + DRF REST API for the GoCart React frontend (repo: `../ecom`). **The frontend is the source of truth for the API
shape**: endpoints, field names and the response envelope come from what `../ecom/src` actually calls and reads.

## Stack (fixed, do not change)

Python + Django (5.2 LTS) + Django REST Framework · PostgreSQL installed locally (never SQLite, not even in dev) ·
JWT via djangorestframework-simplejwt · OpenAPI via drf-spectacular · config via django-environ (`.env`) ·
django-cors-headers. Celery and Redis are NOT set up; ask before adding them.

## Working rules

- Run backend commands only as `cd <backend-dir> && source venv/bin/activate && <cmd>` (Windows:
  `venv\Scripts\activate`), where `<backend-dir>` is the absolute path of THIS repo's root. Never run `manage.py` or
  `pytest` from the frontend folder. [PROJECT] write the absolute path here for the new project (or keep it in Claude's memory).
- Backend git: `git -C <backend-dir> ...`. [PROJECT] Frontend (`ecom/`) and backend are separate repos: never mix
  their commits; each gets its own commit message.
- No Docker, docker-compose or Dockerfile. Local setup = Python virtualenv + local PostgreSQL. Setup steps live in
  README.md; keep `requirements.txt`, `requirements-dev.txt` and `.env.example` current.
- Never change a frontend API call, type or file without asking first; propose the change and wait.
- During implementation, show each step's result to the user BEFORE committing.

## Commands

```bash
python manage.py runserver | migrate | makemigrations | createsuperuser
pytest                                   # every step must end green
python manage.py spectacular --file openapi.yaml --validate --fail-on-warn   # commit the result: a test compares it
python scripts/e2e_smoke.py              # a whole customer visit against the RUNNING dev server (dev DB only)
python manage.py setup_roles             # create/update the Catalog Manager & Order Manager groups (safe in prod)
scripts/backup.sh                        # back up the database + media (cron; see README > Backups)
```

Every push/PR to `main` runs `pytest` + schema validation in GitHub Actions (`.github/workflows/ci.yml`); keep it green.

## Structure

`config/settings/{base,dev,prod}.py` · `config/api_urls.py` (everything under `/api/v1/`) · `config/frontend_calls.py` ·
`scripts/` (`e2e_smoke.py`, `backup.sh`) · `.github/workflows/ci.yml` ·
`apps/{core,accounts,addresses,catalog,content,siteconfig,wishlist,cart,orders,payments,reviews,notifications,coupons,returns,dashboard}` (built step by step) ·
`docs/API_CONTRACT.md` · `docs/ROADMAP.md` (what's built vs. still missing, priority order) · `openapi.yaml`

## API contract

[PROJECT] Canonical: `docs/API_CONTRACT.md`. Generated schema: `openapi.yaml` and `/api/docs/`. Change the contract doc and the
schema together, and never diverge from what the frontend calls without the user's approval.

## Conventions

- Every response uses the envelope `{success, message, data}`; errors are
  `{success:false, message, error (string), errors (string[]), field_errors?}`. Views return `Response(data)` or
  `api_response(data, message=...)`; never hand-build the envelope (renderer + `envelope_exception_handler` do it).
- Money: `DecimalField(12, 2)` and `apps/core/money.py` only, never `float`. On the wire money is a JSON number
  (`COERCE_DECIMAL_TO_STRING=False`), because the frontend does arithmetic and `.toFixed()` on it.
- Stock/orders: only through `orders.services.place_order()` (and `take_back_stock()` for goods a customer sent back) inside `transaction.atomic()` with `select_for_update()`
  (lock variants in id order, then products, then the day's order counter). Order status changes only through
  `orders.services.change_status()`, which checks the transition map in `orders/state.py` and always writes
  `OrderStatusHistory`. Prices are always recomputed from the database, never taken from the request.
- The delivery estimate is the shipping type's `DeliveryCharge.min_days` / `max_days` (both empty = no promise, shown nowhere); `place_order`
  snapshots it as `Order.expected_from` / `expected_to` (calendar days from the order's day) and `services.expected_delivery(order)` is the only
  place that decides whether to show it (only while the order is on its way). `GET /orders/?status=` takes one status or a comma list.
- Placing an order is safe to repeat: `POST /orders/` takes an optional `Idempotency-Key` header, and `orders.services.place_order_once(user, data, key)`
  (one transaction) answers a repeat with the order the key already placed instead of placing another (`OrderRequestKey`: key, owner = the signed-in
  user or the guest's phone, a hash of the order asked for, the order). A `pg_advisory_xact_lock` on (owner, key) makes two requests with the same
  key take turns (the second finds the first's row, or places the order itself if the first was refused and rolled back). The same key for a
  different order is `KeyReused` (409); a refused order leaves no row; without the header `place_order` runs as before. The key is checked in the view
  (`idempotency_key`, 8-64 token characters, else 400) and `CORS_ALLOW_HEADERS` lists `idempotency-key`.
- Customers read their orders through `orders.services.customer_orders / customer_order / tracked_order` and cancel only
  through `orders.services.cancel_order()` (pending only, under the order's row lock, via `change_status`). The order
  serializers never show the staff's history note or `changed_by`; the guest tracking view (`orders/track/`, public,
  scope `order_track`) never shows name, e-mail, phone or address. `orders` learns the payment of an order through
  `orders.hooks` (the payments app registers a provider), never by importing `payments`.
- Payments: a `Payment` is opened and moved only by `apps/payments` (transition map in `payments/state.py`), driven by
  the `orders.signals` (`order_placed`, `order_status_changed`, sent with `send()` inside the order's transaction so a
  failure rolls both back). `orders` never imports `payments`. `order_placed` receivers run before the order number
  exists and must not use it (do e-mail/SMS in `transaction.on_commit`).
- Notifications: `apps/notifications` sends the customer an SMS (and e-mail, if given) when an order is placed and
  when its status becomes confirmed/shipped/cancelled/refunded (delivered is e-mail-only; paid/returned stay
  silent) — each event has its own on/off switch in `NotificationSettings` (one admin row, superuser-only, like
  `SiteSettings`), checked in `apps/notifications/services.py` before composing the message. Its `apps.py` connects
  to the same `orders.signals` as payments, but unlike payments' receivers, **both** `on_order_placed` and
  `on_order_status_changed` always defer the actual send to `transaction.on_commit` — `order_placed`'s order has no
  number yet, and even `order_status_changed` must not hold its row lock open across what would be a network call,
  nor let a "sent" message survive a later rollback of the same transaction. A delivery failure is only logged,
  never raised: an order must never fail because a notification could not go out. Pluggable like OTP
  (`NOTIFICATION_BACKEND`, dotted path; `ConsoleNotificationBackend` logs to the console) — but unlike
  `OTP_BACKEND`, `prod.py` does **not** require a real class here, since no notification is safety/security-critical
  the way OTP delivery is.
- Coupons: `apps.coupons.services` is the only code that reads or redeems a `Coupon`. `place_order()` calls
  `apply_coupon_to_order()` inside its own transaction, after the real subtotal is known — never against a
  client-sent discount — and locks the coupon row after the variants but before the day's order-number counter
  (extending `place_order`'s own lock order, see its module docstring). `change_status()` calls
  `release_coupon_usage()` on a move to `CANCELLED`, before it restocks, for the same lock-order reason: a customer
  who cancels and retries is not blocked by their own cancelled attempt. `POST /coupons/validate/` previews the
  discount (guest-writable, `ScopedRateThrottle` scope `coupon`) but is not required — `POST /orders/` redeems a
  `coupon_code` on its own.
  `GET /coupons/available/` (scope `coupon_offers`) suggests the coupons flagged `show_at_checkout` (which need a
  `public_title`) that can be used right now; `services.available_offers()` asks `_eligibility_problem` itself, so the list can
  never disagree with `validate`, and it is a hint only (`eligible` / `amount_short` are for drawing, `POST /orders/` decides).
- Returns: `apps/returns` (depends on `orders`, never the other way round: `orders` shows the customer's `returns` block through
  `orders.hooks.returns_info`, which the returns app registers in `ready()`, like the payments block). A `ReturnRequest` is NOT an order status:
  it holds lines and units of a DELIVERED order (`ReturnItem`), opened only by `services.request_return()` (the order row locked, so two taps
  can not both take the last unit) and moved only by `services.change_status` / `staff_update` / `receive_goods` through `state.py`
  (`requested -> approved | rejected | cancelled`, `approved -> received | cancelled`, `received -> completed`). Units held = requested, approved,
  received and completed requests (`state.HOLDING`); a rejected or cancelled one frees them. The window and the return charge are `ReturnSettings`
  (one admin row, Owner only; defaults 7 days after the delivery history row, `enabled` on, `charge_return_delivery` on; reading never writes).
  Money per request, all snapshots: `goods_amount` (lines less their coupon share), `courier_cost` (the order's delivery charge), `return_charge`
  (what the customer pays of it: 0 for the shop's own fault, `ReturnRequest.FREE_REASONS`, or when the policy charges nothing; staff may waive it),
  `refund_amount = goods - charge` (a new charge moves it, staff may type another figure until the request is rejected, completed or cancelled),
  `shop_cost = courier_cost - return_charge` (the courier the shop pays out of its profit; never in the API). **Inventory:** `receive_goods()` is the
  only place the stock moves for a return: under the request's row lock it records per line the units that came back fine (`good_quantity`, put back on
  the shelf) and damaged (`damaged_quantity`, only counted in `ProductVariant.damaged_quantity`, never sellable) through
  `orders.services.take_back_stock()` (variants locked in pk order like every other stock writer), once. It never touches the order, a payment or
  `total_orders`; the money is paid back by hand. Staff enter the numbers in the request's inline (editable only while `approved`; saved when the
  status is set to Received by `ReturnRequestAdmin.save_related`). The dashboard subtracts completed refunds in its own line ("Net revenue") and shows
  the shop-paid courier and the damaged units. The customer sees `response` (the shop's message). Order Manager may view/change requests and their
  lines (`setup_roles`); add/delete stay blocked.
- Stock history: every move of a variant's stock leaves a `catalog.StockMovement` (signed `change`, `damaged_change` for returned units that are
  only counted, `stock_after`, `kind`, `reference`, `by`), written ONLY through `catalog.stock.record`, in the same transaction as the move: `place_order`
  (kind sold, after the order number is taken, because the line carries it), `_restock` (order put back), `take_back_stock` (returned goods, one line per
  variant, damaged units included) and `ProductVariant.save` (a hand-edit or a new variant with stock: measured against the row locked at save time,
  never against what the form showed; the admin sets `variant.changed_by`). The product page's variant formset (`ProductVariantFormSet.save_existing`)
  writes the stock only when the person changed the box (the box keeps a hidden copy of what it showed, `show_hidden_initial`) and never
  `damaged_quantity`, so a save does not undo an order or a return that landed while the page was open. `queryset.update()` / `bulk_create` send no `save`: a code path that moves stock
  that way must call `record` itself. Lines are never edited or deleted (the admin is read-only, Catalog Manager may view); `variant` is SET_NULL with the
  SKU and name copied. No backfill: stock from before has no lines. No API, no frontend.
- Stock notice ("Only N left"): `catalog.StockNotice` (one row, `show_when_left`, default 5, 0 = off; Catalog Manager may change it, add/delete
  blocked) and `catalog/stock_notice.py` (`threshold`, `left_if_low`) are the only code that decide it. The product API answers `stock_left`
  (the real number when 1..threshold are in stock, else null: never the real stock of a well-stocked product). A card says it only for a product
  without options (`has_options` false; the stock comes from the `list_stock` annotation of `with_list_fields`, the same default variant the card's
  price comes from); a product with options says it on each size and on a colour sold without a size, in `build_options`. The serializers read the
  threshold once per response (`_notice_at`, one query), and reading never creates the row (`StockNotice.current()`; `load()` is for the admin).
- Flash sale: products and categories are marked `is_flash_sale` in the catalog; the optional **window** that says when the
  mark counts is `catalog.FlashSale` (one row, `starts_at` / `ends_at`; none set = the mark counts always, as before).
  `catalog/flash_sale.py` (`flash_sale_state`, `is_live`) is the only code that reads it: `FlashSaleProductsView` adds
  `flash_sale` (the window and the seconds left, measured here so a customer's clock does not matter) to its page and
  returns nothing while the sale is not live, and the flash-sale categories follow the same window. It lives in
  `catalog`, not `siteconfig`, because `siteconfig` knows nothing about products. Catalog Manager may change it
  (`setup_roles`); add/delete stay blocked in its admin.
- Announcement bar: free text in `siteconfig.SiteSettings` (`announcement_*`), with an optional `announcement_ends_at`.
  `siteconfig.services.announcement(site, now)` decides what `GET /site/` answers: `null` when it is off, empty, or its end
  has passed, else `{text, link, ends_in_seconds}` (seconds measured here, like the flash sale's). The bar is NOT tied to the
  flash sale: `siteconfig` must not know products, so the admin sets the end by hand.
- Dashboard: `apps/dashboard` is Django-admin-only (Admin > Dashboard) — no DRF views, no API, no frontend change,
  since `../ecom` has no staff UI to call one from. `services.py` holds every aggregation as a plain read-only
  query; revenue is defined as the sum of `Payment.amount` where `status == PAID`, bucketed by `paid_at` (not
  `Order.created_at`) — self-correcting, so a later refund drops back out of whatever period it once counted
  toward. Owner-only like `SiteSettings`/`NotificationSettings`: never added to either Group in `setup_roles.py`,
  relying on Django's default `has_view_permission` (a superuser bypasses every check; nobody else has the
  permission). `DashboardReport` is a `managed=False` marker model with no table, existing only to give the admin
  something to register a menu entry on.
- Error tracking: `SENTRY_DSN` is optional (empty = off, the default everywhere but a real deployment) —
  `config/settings/base.py` calls `sentry_sdk.init(send_default_pii=False)` only when it's set, so no phone
  number, e-mail, IP or cookie ever leaves in a report. Unlike `OTP_BACKEND`, prod does not require it.
- Reviews: written only through `reviews.services.create_review()` / `update_review()` (needs a DELIVERED order of the
  customer containing the product; one per customer and product). The product's `total_reviews` / `avg_rating` are
  derived data: `refresh_product_rating()` recounts them from the approved reviews (locking the product row first),
  and the `post_save` / `post_delete` receivers of `Review` call it, so the API, the admin and cascades all keep it
  right. Nothing writes those two columns by hand. `bulk_create` and `queryset.update()` send no signals: recount
  yourself. Uploads: type from the bytes (`core.validators.detect_media_format`), stored name gets the matching
  extension, API `media_urls[].type` is the MIME type.
  `GET /products/reviews/featured/` (homepage) is `services.featured_reviews()`: the reviews the staff ticked
  (`Review.show_on_homepage`) if any can be shown, else the shop's own pick (4-5 stars, a 40+ character comment, a
  delivered purchase, one per customer); max 8, `short_name()` ("Rahim U.") is the only name it gives away.
- Requests: `core.middleware.UploadSizeLimitMiddleware` answers a multipart upload over `MAX_UPLOAD_REQUEST_MB` with a
  413 before reading it; `envelope_exception_handler` turns Django's `SuspiciousOperation`s (body over
  `DATA_UPLOAD_MAX_MEMORY_SIZE`, too many fields/files) into 413/400, never a 500.
- Throttles: every view has the generous default (`anon` / `user`); a view that lets a GUEST write must set
  `throttle_classes = [ScopedRateThrottle]` + `throttle_scope` (a test walks the URLconf and fails otherwise). The client
  IP comes from `NUM_PROXIES` (mandatory in prod): never read `X-Forwarded-For` yourself.
- Product counters (`Product.COUNTER_FIELDS`: views, orders, reviews, rating) are only moved by code; the admin saves a
  product with `save_without_counters()` so it never writes back stale ones.
- `.env.example` lists every variable `config/settings/*.py` reads (a test checks), values without inline comments
  (django-environ would keep the comment as part of the value).
- The frontend's calls are listed in `config/frontend_calls.py` (spelled as `ecom/src` writes them). A change to the API
  means: that list, `docs/API_CONTRACT.md`, `openapi.yaml` (regenerate, commit), and `scripts/e2e_smoke.py` if the flow
  changes; `config/tests` and the smoke fail until they agree.
- Status codes matter to the frontend: bad OTP/validation/out-of-stock = 400; 401 ONLY for missing/expired/invalid
  tokens (a 401 makes the frontend try to refresh, then log the user out).
- `apps/accounts` (and `core`) must not import shop apps (catalog/cart/orders...): this base is reused for other
  projects. Cross-app hooks go through signals, e.g. `accounts.signals.guest_data_received` (guest cart/favorites
  sent at sign-in; the cart/wishlist apps connect a receiver). Receivers run with `send_robust`.
- Staff access is two Django Groups (`Catalog Manager`, `Order Manager`), kept in sync by
  `apps/accounts/management/commands/setup_roles.py` — `group.permissions.set(...)`, not `.add()`, so editing that
  file's permission tables and rerunning the command corrects an existing group everywhere it's run, not just adds.
  It looks up permissions by `app_label`/`codename` string (never imports catalog/orders/etc., per the rule above)
  and never touches a `User`'s `groups` or `user_permissions` — assigning someone to a role stays a manual step in
  Admin > Users. The Owner role is `is_superuser=True`, never a Group. Never grant a permission a ModelAdmin already
  blocks with a `has_*_permission` override (see the file's own docstring for the current list) — the block should
  stay the single source of truth, not a permission relied on "just in case".
- A DRF view with `authentication_classes = []` must define `get_authenticate_header()`, otherwise DRF turns every 401
  into a 403 (see `PublicAuthView`). Public auth views ignore the Authorization header on purpose: the frontend sends
  its stale access token to refresh/logout.
- OTP delivery is pluggable via `OTP_BACKEND` (`apps/accounts/otp/backends.py`). Only `ConsoleOTPBackend` and
  `BrowserOTPBackend` may print a code, and prod has no default backend. `BrowserOTPBackend` is DEBUG only: it also
  shows the code in the `message` of the register / login / resend-otp / request-otp responses (through
  `IssuedOTP.dev_code`, never stored), raises `ImproperlyConfigured` when `DEBUG` is off, and `config.settings.prod`
  refuses to start with it. No other backend may put a code in a response.
- Both `/x` and `/x/` must resolve with no redirect: register routes with `apps.core.urls.dual_path`. `APPEND_SLASH=False`.
- Views stay thin, logic lives in `services.py`; serializers validate; permissions per view. The default permission is
  `IsAuthenticated`, so public endpoints must say `permission_classes = [AllowAny]`.
- Uploads: `ImageField(upload_to=RandomUploadTo("folder"), validators=[validate_image_upload])` (apps/core): random
  file names, real-format + size check, delete the old file in `transaction.on_commit` when replacing. Tests never write to
  `./media` (conftest points MEDIA_ROOT at a temp dir).
- Uploads: validate type and size. HTML fields are sanitized with nh3 on write. Never log OTPs; mask phone numbers.
- Tests with pytest-django. Every step ends with `pytest` green and `spectacular --validate --fail-on-warn` clean.
