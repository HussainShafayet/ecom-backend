# GoCart Backend

Django + Django REST Framework API for the GoCart React storefront (`../ecom`). PostgreSQL, JWT (simplejwt),
OpenAPI via drf-spectacular. The API shape is dictated by the frontend, see [docs/API_CONTRACT.md](docs/API_CONTRACT.md).

No Docker: a Python virtualenv plus a locally installed PostgreSQL.

> **Template:** `config/`, `apps/core` and `apps/accounts` are a reusable base (tag `template-base-v1`). To start another
> project from it, follow [docs/NEW_PROJECT.md](docs/NEW_PROJECT.md).

## Requirements

- Python 3.12+ (developed on 3.14)
- PostgreSQL 14+ installed and running on this machine (SQLite is not supported, not even for dev)

## 1. PostgreSQL (once)

Create an application role and database. The role needs `CREATEDB` because pytest creates a `test_gocart` database.

```bash
# Linux (Fedora: `sudo dnf install postgresql-server postgresql-contrib && sudo postgresql-setup --initdb && sudo systemctl enable --now postgresql`)
# (Debian/Ubuntu: `sudo apt install postgresql postgresql-contrib`)
sudo -u postgres psql <<'SQL'
CREATE ROLE gocart WITH LOGIN PASSWORD 'gocart' CREATEDB;
CREATE DATABASE gocart OWNER gocart;
SQL
```

macOS (Homebrew): `brew install postgresql@17 && brew services start postgresql@17`, then run the same SQL with
`psql postgres`. Windows: install PostgreSQL from postgresql.org, then run the SQL in `psql -U postgres`.

Check it works (use `127.0.0.1`, not `localhost`):

```bash
psql "postgres://gocart:gocart@127.0.0.1:5432/gocart" -c "select 1"
```

## 2. Project setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                # then put a real SECRET_KEY in it (command inside the file)
python manage.py migrate
python manage.py createsuperuser    # phone (+8801XXXXXXXXX), name, password: only staff have passwords
python manage.py runserver
```

Then open:

| URL | What |
|---|---|
| http://127.0.0.1:8000/api/v1/health/ | API + database check |
| http://127.0.0.1:8000/api/docs/ | Swagger UI (OpenAPI) |
| http://127.0.0.1:8000/admin/ | Django admin (staff) |

### Signing in during development (OTP)

Customers have no password: they sign up / sign in with a phone number and a 6-digit code. In dev the code is not
sent anywhere, it is **printed in the `runserver` terminal**:

```
WARNING apps.accounts.otp [DEV ONLY] OTP for +8801712345678 (register): 402885
```

Type that into the frontend's OTP page. Codes expire after 5 minutes (`OTP_TTL_SECONDS`), allow 5 wrong tries, and can be
resent every 60 s. To plug in a real SMS/email provider, write a class with
`send(self, *, target, code, purpose)` (see `apps/accounts/otp/backends.py`) and set `OTP_BACKEND` to its dotted path.

Staff (Django admin) are the only users with passwords: `python manage.py createsuperuser`.

### See the OTP in the browser (development)

Switching to the `runserver` terminal for every code gets old. With the development-only `BrowserOTPBackend` the code
is also appended to the `message` the frontend already displays after sign up, sign in, "resend" and the profile
"send OTP" (nothing to change in the frontend):

```
OTP sent to +88017****5678. [DEV] Your code is 402885.
```

Turn it on by setting this line in `.env` (keep `DEBUG=True`) and restarting `runserver`; remove it (or point it back
at `ConsoleOTPBackend`) to go back to printing in the terminal:

```
OTP_BACKEND=apps.accounts.otp.backends.BrowserOTPBackend
```

It still logs the code like the console backend. Guards: it refuses to work unless `DEBUG` is `True` (OTP requests
then answer `503`, the reason is in the server log), `config.settings.prod` refuses to start with it, and the default
stays `ConsoleOTPBackend`. Use it on your own machine only: anyone who can reach the API can read the codes.

### Uploaded files (profile pictures)

In dev they are stored in `backend/media/` (gitignored) and served by `runserver` at `/media/...`; the API returns
absolute URLs. JPEG/PNG/WebP up to `MAX_IMAGE_UPLOAD_MB` (5). In production keep them on a volume that the reverse
proxy serves at `/media/`, or in an S3-compatible store (see "Production notes").

### Point the frontend at it

In `../ecom/.env`:

```
VITE_BASE_URL=http://localhost:8000/api/v1/
```

The trailing slash matters: the frontend builds some URLs as `${VITE_BASE_URL}accounts/token/refresh/`.
`.env` here already allows the frontend origin `http://localhost:3000` through `CORS_ALLOWED_ORIGINS`.

## Everyday commands

Always from the backend folder with the virtualenv active.

```bash
pytest                                                           # all tests
pytest apps/core -q                                              # one app
python manage.py makemigrations && python manage.py migrate
python manage.py spectacular --file openapi.yaml --validate --fail-on-warn   # regenerate + validate schema
python manage.py check --deploy --settings=config.settings.prod              # production readiness (needs prod env vars)
python manage.py seed_catalog && python manage.py seed_content               # demo products, sliders and banners (dev only)
```

## Orders (staff)

Customers place orders at checkout; staff manage them in the Django admin under **Orders**. An order can neither be
added nor deleted, and only its status can be edited (the form offers the current status and the allowed next ones; the
list has the bulk actions Mark as paid / shipped / delivered and Cancel and restock, which puts the goods back into
stock). **Delivery charges** are two rows, Inside Dhaka (60.00) and Outside Dhaka (120.00) by default, created by a
migration; edit the amount there (placed orders keep the amount they were charged). Order numbers look like
`GC-20260923-0001` (`ORDER_NUMBER_PREFIX`); `THROTTLE_ORDER` limits how often one client can place orders.

Every order also has a **payment** (cash on delivery: pending when placed, paid when the order is delivered or marked
paid, cancelled or refunded when the order is). Staff see them, read-only, under **Payments**; move the order and the
payment follows.

## Production notes

Run `python manage.py check --deploy` with the production environment: it must say "no issues" (a test runs it).

- `DJANGO_SETTINGS_MODULE=config.settings.prod`, `DEBUG` off, real `SECRET_KEY`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`.
  Move the staff login off the obvious address with `ADMIN_URL=staff-9f3k/`.
- **`OTP_BACKEND` has no default in prod**: startup fails until you point it at a real delivery class
  (`BrowserOTPBackend`, which shows codes in API responses, is rejected).
- **`NUM_PROXIES` has no default in prod** either: the number of reverse proxies in front of Django (nginx alone = 1,
  a CDN in front of nginx = 2). It decides which address the throttles count: too low and every customer shares the
  proxy's address (one limit for everybody), too high and a client chooses its own address with an
  `X-Forwarded-For` header and dodges every limit. The proxy must append to that header
  (`proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`) and pass `X-Forwarded-Proto`, with
  `SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https` so Django knows the request was HTTPS.
- Rate-limit counters live in a database cache shared by all workers. Create its table once:
  `python manage.py createcachetable`. Every request reads and writes one counter (the generous default limits,
  `THROTTLE_ANON` / `THROTTLE_USER`); a busy shop may prefer `limit_req` in the proxy and very high values here.
- **Body size.** The API refuses a multipart upload over `MAX_UPLOAD_REQUEST_MB` (default 255: five review videos of
  50 MB and the text) with a 413 before it reads it, and any other body over `DATA_UPLOAD_MAX_MEMORY_SIZE` (2.5 MB).
  Make the proxy stop the transfer earlier, small everywhere and large only where files are uploaded:

  ```nginx
  location /api/ { client_max_body_size 1m; proxy_pass http://gocart; }
  location ~ ^/api/v1/(products/reviews|accounts/profile)/?  { client_max_body_size 260m; proxy_pass http://gocart; }
  ```
- **Static and media files.** `python manage.py collectstatic` (admin CSS) into `STATIC_ROOT` and let the proxy serve it at
  `/static/`. Uploads are on the local disk (`MEDIA_ROOT`, served at `/media/`) unless you install
  `django-storages[s3]` and set `MEDIA_STORAGE_BACKEND=storages.backends.s3.S3Storage` with
  `MEDIA_STORAGE_OPTIONS={"bucket_name": "...", "endpoint_url": "...", "access_key": "...", "secret_key": "..."}`;
  the API then returns the store's own URLs.
- Blacklisted refresh tokens pile up. Purge expired ones regularly (cron, e.g. daily):
  `python manage.py flushexpiredtokens`
- Logs go to the console (`LOG_LEVEL`). Only the dev-only console OTP backend prints a code and a phone number (prod
  has no default backend); nothing else logs either. A refused request (too big, hostile) is a WARNING, an unexpected
  error an ERROR with the traceback.
- **Editing stock in the admin** overwrites the number the form was opened with: an order placed meanwhile is lost from
  the stock count. Do stock corrections when the shop is quiet. (The product's own counters, orders/views/reviews/rating,
  are left alone by an admin save.)

## Layout

```
config/            settings/{base,dev,prod}.py, urls.py, api_urls.py (everything under /api/v1/)
apps/core/         response envelope, error handling, pagination, money helpers, URL helper, health check
apps/accounts/     custom phone User, OTP register/login, JWT refresh/logout, profile (+ OTP-verified phone/email change, picture)
apps/addresses/    saved shipping addresses (shop-specific, not part of the template base)
apps/catalog/      categories, brands, products, variants, media; the public product/category API and /content/shop
apps/content/      editable sliders and banners of the six shop pages (/content/pages/<page>/)
apps/wishlist/     favourites (/accounts/favourite/) and the catalog's `is_favourite`
apps/cart/         the signed-in cart (/accounts/cart/) and the merge of a guest's browser cart at sign-in
apps/orders/       checkout: POST /orders/ (guests too), /content/checkout/, delivery charges, order status flow + admin
apps/payments/     the payment of each order (cash on delivery), following the order's status; provider interface
apps/reviews/      product reviews (/products/reviews/): only after a delivered order, photos/videos, the product's rating
docs/API_CONTRACT.md   canonical API contract (what the frontend calls)
openapi.yaml       generated schema (keep in sync: see command above)
```

## Settings

`DJANGO_SETTINGS_MODULE` and everything else come from `.env` (see `.env.example`). `config.settings.dev` is the
default for `manage.py`; deployed environments set `DJANGO_SETTINGS_MODULE=config.settings.prod`.

## Troubleshooting

- `password authentication failed for user "gocart"`: role/password differs from `DATABASE_URL`, or you used
  `localhost` instead of `127.0.0.1`.
- `permission denied to create database` when running pytest: the role lacks `CREATEDB`
  (`sudo -u postgres psql -c "ALTER ROLE gocart CREATEDB"`).
- `connection refused`: PostgreSQL isn't running (`sudo systemctl start postgresql`).
