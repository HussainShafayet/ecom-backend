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
| 2 | Staff roles | Every staff user had `is_staff=True` with no Groups, so anyone made staff saw and could edit everything (orders, payments, customers) just to fix a product listing. | **In progress** — step 14. |
| 3 | Order notifications (SMS/e-mail) | A customer places an order and hears nothing again until they check the site themselves — no "confirmed", "shipped", "delivered" message. | Not started. |
| 4 | Coupon / promo codes | Almost every shop needs these for marketing. | Not started. |
| 5 | Admin dashboard / reports | Today the admin is just Django's model list pages — no at-a-glance revenue, order count, low-stock or top-product view. | Not started. |
| 6 | Courier integration (Pathao/Steadfast/RedX) + tracking numbers | Needed for a real Bangladesh COD shop; right now delivery is entirely manual. | Not started. |
| 7 | Payment gateway (bKash/Nagad/SSLCommerz) | Cash on delivery only today; no provider has been chosen yet. | Not started. |
| 8 | CI (GitHub Actions), error tracking (Sentry), backups | None of this exists yet. | Not started. |

## Later (P2, not launch-blocking)

Customer-initiated return/refund requests, invoice/receipt printing, low-stock alerts + stock history, related /
recently-viewed / back-in-stock products, SEO (page titles, meta, sitemap), product CSV import/export, newsletter
sending (subscribers are already collected — see item 1), abandoned-cart recovery, district-level delivery charges,
VAT handling.

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
