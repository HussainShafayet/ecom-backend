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
