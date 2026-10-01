# Roadmap

An audit of GoCart against standard e-commerce practice, and the priority-ordered list of what's missing before
launch. Written 2026-09-24, updated as each step lands — keep it in sync instead of letting it drift.

## What's already there

Catalog, search/filter, variants, cart + guest cart, wishlist, guest checkout, cash on delivery, delivery charges,
order history/cancel/tracking, reviews (photo/video), phone+OTP auth, profile/addresses, CMS banners and sliders
(`apps/content`), the order/payment status flow, the Django admin, request throttling/security/CORS, and a large
test suite.

## What's missing (launch order)

| # | What | Why it matters | Status |
|---|---|---|---|
| 1 | Site settings + static page CMS + contact form + newsletter | The shop's own identity (name, logo, contact, social links, About/Privacy/Terms, FAQ) was hardcoded in the frontend — a developer had to ship code to change a phone number. | **Done** — `apps/siteconfig` (step 13), merged. |
| 2 | Staff roles | Every staff user had `is_staff=True` with no Groups, so anyone made staff saw and could edit everything (orders, payments, customers) just to fix a product listing. | **Done** — `apps/accounts/management/commands/setup_roles.py` (step 14), merged. |
| 3 | Order notifications (SMS/e-mail) | A customer places an order and hears nothing again until they check the site themselves — no "confirmed", "shipped", "delivered" message. | **Done** — `apps/notifications` (step 15), console/log backend only; a real SMS/e-mail provider is not wired up yet. Each event has its own on/off switch (admin > Notifications). |
| 4 | Coupon / promo codes | Almost every shop needs these for marketing. | **Done** — `apps/coupons` (step 16), merged. Percentage/fixed, min order amount, max discount cap, total and per-customer use limits, a validity window and a manual on/off switch, all admin-editable. `POST /coupons/validate/` previews the discount; `POST /orders/` redeems `coupon_code` directly. Frontend: a promo-code field in checkout/cart. |
| 5 | Admin dashboard / reports | Today the admin is just Django's model list pages — no at-a-glance revenue, order count, low-stock or top-product view. | **Done** — `apps/dashboard` (step 17), a Django-admin-only page (Admin > Dashboard), Owner-only. Revenue (today/week/month/all-time, from paid payments), order counts by status, top products, low stock, coupon redemptions, new customers. No API, no frontend change — nothing here is called by `../ecom`, which has no staff UI to put it in. |
| 6 | Courier integration (Pathao/Steadfast/RedX) + tracking numbers | Needed for a real Bangladesh COD shop; right now delivery is entirely manual. | Not started. |
| 7 | Payment gateway (bKash/Nagad/SSLCommerz) | Cash on delivery only today; no provider has been chosen yet. | Not started. |
| 8 | CI (GitHub Actions), error tracking (Sentry), backups | None of this exists yet. | **Done** — step 18. `.github/workflows/ci.yml` runs tests + schema validation on every push/PR to main; Sentry is optional (`SENTRY_DSN`, empty = off, no personal data sent); `scripts/backup.sh` dumps the database and media on a cron, see README > Backups. |
| 9 | Trust badges ("free delivery", "easy returns", ...) | A "free delivery / easy returns" strip under the header did not exist, and it could not be added without shipping code. | **Done** — step 19, in `apps/siteconfig`. `GET /site/` gains `trust_badges` (active ones, admin's order); edited inline on Admin > Site settings. `icon` is a fixed choice list the frontend maps to its own icon. Frontend: `layout/TrustBadgeBar` (ecom repo) draws it on every page. |
| 10 | Flash sale window (countdown) | The flash sale had only an on/off mark, so a storefront could not show "ends in 02:14:09" or hide the sale when it is over. | **Done** — step 20, in `apps/catalog`. One optional window (`FlashSale`: `starts_at` / `ends_at`, Admin > Catalog > Flash sale, Catalog Manager may edit it). `GET /products/flash-sale/` gains `flash_sale` (the window and the seconds left, measured by the server) and is empty while the sale is not live; nothing set = the old always-on behaviour. Frontend: a countdown on the homepage section and the flash-sale page (ecom repo). |
| 11 | "Available offers" at checkout | With several coupons a customer had to know a code to get a discount: nothing on the page suggested one. | **Done** — step 21, in `apps/coupons`. `Coupon` gains `show_at_checkout` (default off: secret and influencer codes stay secret) and a customer-facing `public_title` (required once shown), both on the admin form. `GET /coupons/available/?subtotal=` (public, throttled, scope `coupon_offers`) lists up to 5 shown coupons that can be used right now, with `eligible` and `amount_short`. Frontend: tappable chips under the promo box of `CheckoutSummary` that apply the code, and "Add ৳120 more to use FREESHIP" for one out of reach (ecom repo); `POST /orders/` still validates the code on the server. |
| 12 | Real testimonials on the homepage | The storefront's "What Our Customers Say" section was demo data (made-up names, placeholder photos), so it was switched off. | **Done** — step 22, in `apps/reviews`. `Review.show_on_homepage` (default off; tick it on the review form, in the list, or with the bulk action) and `GET /products/reviews/featured/` (public, max 8): the ticked reviews when any can be shown, otherwise the shop's own pick (4-5 stars, a 40+ character comment, a delivered purchase, one per customer). The reviewer is a short name ("Rahim U."), never a phone number or an e-mail address. Frontend: a `Testimonials` section on the homepage that is not drawn while there is nothing to show (ecom repo). |
| 14 | My orders: filter by status, buy again, delivery estimate | The order list could not be narrowed, a past order could not be put back in the cart (its lines said which product, not which variant), and nothing told the customer when to expect a parcel. | **Done** — step 24, in `apps/orders`. `GET /orders/?status=` (one status or a comma list; unknown = 400); every order line carries `variant_id`; `DeliveryCharge.min_days` / `max_days` (empty = no promise, set in Orders > Delivery charges) give `delivery_estimates` on `GET /content/checkout/`, and an order snapshots `expected_from` / `expected_to` and shows `expected_delivery` while it is on its way (also in the answer to `POST /orders/` and in guest tracking). Frontend: status tabs on My orders, a Buy again button, "Delivery in 2-3 days" at checkout and "Expected 5-7 Oct" on the order (ecom repo). |

## Later (P2, not launch-blocking)

Customer-initiated return/refund requests, invoice/receipt printing, low-stock alerts + stock history, related /
recently-viewed / back-in-stock products, SEO (page titles, meta, sitemap), product CSV import/export, newsletter
sending (subscribers are already collected — see item 1), abandoned-cart recovery, district-level delivery charges,
VAT handling. A persisted `NotificationLog` (delivery attempts/failures, for staff visibility) once a real SMS/
e-mail provider is chosen and failures start mattering operationally (see item 3).

## A much bigger, separate idea: SaaS pricing tiers (not started, not scoped)

Raised 2026-09-28 while building item 3: GoCart is currently a reusable *template* (each client gets their own
clone/deployment, per the backend's own docs) — this idea would turn it into an actual multi-tenant SaaS product
sold on subscription tiers (e.g. "Normal"/"Premium"), where a shop's tier gates which features it can use. The
first concrete case raised: which order-notification *types* a shop may enable (see item 3's `NotificationSettings`
toggle) would depend on its plan, not be freely switchable by every shop.

This is genuinely a separate, large initiative — subscription/billing, a plan model, and a feature-gating
convention that would eventually need applying consistently across every feature, not just notifications — and
should not be bundled into any single feature step. Deliberately **not started and not designed yet**. When it is
picked up: item 3's per-event `NotificationSettings` toggle is exactly the mechanism a plan-tier gate would sit in
front of (a plan would just narrow *which* toggles a shop is allowed to turn on), so today's work here is not
wasted by waiting.

## Small frontend cleanup (offered, not yet done)

Nothing here is a missing feature — it's dead code worth removing in a small dedicated PR:
- `ecom/src/context/CartContext.js` — an unused, standalone cart implementation (the real cart is `cartSlice.js`).
- The dead route `/products/category/:category` (nothing links to it) and the dead `/deals` link in the old
  announcement bar (replaced by the real announcement bar in step 13).
- ~28 blocks of commented-out code scattered through the frontend (an old `WishList` implementation, disabled
  middlewares, etc.).
- `checkoutSlice`'s dead credit-card fields (`cvv`, `expiryDate`) — there is no card payment method yet.

## A note on user roles

**Guest** (no login) and **Customer** (phone+OTP login) are unaffected by any of this — they're covered already.
For staff: **Owner/Super Admin** is simply Django's `is_superuser=True` (already bypasses every permission check,
never a Group); **Catalog Manager** and **Order Manager** are the two Groups added in step 14; a **Delivery
agent** role (a courier-facing, mobile-sized "mark delivered/returned" screen) is deferred until courier
integration (item 6) makes it worth building.
