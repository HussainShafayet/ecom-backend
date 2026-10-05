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
| 13 | Mid-page promo banner, and the words on a slide's button | The homepage could only show banners beside the hero, and the button over a slide always said "Shop Now". | **Done** — step 23, in `apps/content`. A new placement, `mid_banner` (a wide image, one active per page, the Home page only), and `ContentItem.cta_label` (default "Shop Now", empty = no button), on the page's admin form; `GET /content/pages/{page}/` gains `mid_banner` and `cta_label`. Frontend: `MidBanner` between the homepage's sections, and the hero slider's button says what the admin wrote (ecom repo). |
| 14 | An end for the announcement bar | The bar above the header is free text, so "Flash Sale! 50% Off" stayed up after the sale was over until an admin remembered to switch it off. | **Done** — step 24, in `apps/siteconfig`. `SiteSettings.announcement_ends_at` (optional, in the Announcement bar section of Admin > Site settings; empty = until switched off, as before). `GET /site/` answers `announcement: null` once it has passed and otherwise adds `ends_in_seconds` (measured by the server) so an open tab can hide the bar on time. The bar is not tied to the flash sale: `siteconfig` knows nothing about products. Migration `siteconfig/0003` (a nullable column). |
| 15 | Customer return requests | A customer who got the wrong or a damaged item could only phone the shop: nothing on the site let them ask, and nothing told the shop which lines and which units, who pays the courier, or what happens to the stock. | **Done** — step 25, in the new `apps/returns`. A delivered order can be returned for `window_days` days after delivery (Admin > Returns > Return settings: on/off, the days, 7 by default, and whether the customer pays the return delivery). `POST /orders/{order_id}/returns/` takes lines and units with a reason (`other` needs a few words), `POST /orders/{order_id}/returns/{id}/cancel/` calls it off while the shop has not answered, and `GET /orders/{order_id}/` gains `returns` and `items[].id`. **Return charge = the order's delivery charge**, paid by the customer (taken off the refund) for their own reasons and free when the shop was at fault (damaged, wrong item, not as described); staff may waive it, and what the customer does not pay is the courier cost the shop bears. Staff approve, reject, **receive the goods** and complete a request in Admin > Returns (Order Managers may): receiving enters, per line, the units that came back fine (back on the shelf) and the damaged ones (counted in the new `ProductVariant.damaged_quantity`, never sellable). The dashboard gains *Refunded for returns*, *Net revenue* and a Returns block. A request is not an order status: the order stays delivered, the money is paid back by hand. Frontend: *Return items* on the order page (ecom repo). Not done: a message to the customer when the shop answers (a notification event for it). |

## Later (P2, not launch-blocking)

a profit report (needs a cost price on each product and a place to enter the shop's own costs: rent, salary, packaging, marketing, courier; then profit = net revenue - cost of the goods sold - costs - the courier the shop pays for returns - the damaged units; asked for 2026-10-05, not started), invoice/receipt printing, low-stock alerts + stock history, related /
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
