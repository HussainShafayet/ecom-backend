# CLAUDE.md — GoCart Backend

Django + DRF REST API for the GoCart React frontend (repo: `../ecom`). **The frontend is the source of truth for the API
shape**: endpoints, field names and the response envelope come from what `../ecom/src` actually calls and reads.

## Stack (fixed, do not change)

Python + Django (5.2 LTS) + Django REST Framework · PostgreSQL installed locally (never SQLite, not even in dev) ·
JWT via djangorestframework-simplejwt · OpenAPI via drf-spectacular · config via django-environ (`.env`) ·
django-cors-headers. Celery and Redis are NOT set up; ask before adding them.

## Working rules

- Run backend commands only as
  `cd /home/shafayet/Desktop/personal/e-commerce/backend && source venv/bin/activate && <cmd>`
  (Windows: `venv\Scripts\activate`). Never run `manage.py` or `pytest` from the frontend folder.
- Backend git: `git -C /home/shafayet/Desktop/personal/e-commerce/backend ...`. Frontend (`ecom/`) and backend are
  separate repos: never mix their commits; each gets its own commit message.
- No Docker, docker-compose or Dockerfile. Local setup = Python virtualenv + local PostgreSQL. Setup steps live in
  README.md; keep `requirements.txt`, `requirements-dev.txt` and `.env.example` current.
- Never change a frontend API call, type or file without asking first; propose the change and wait.
- During implementation, show each step's result to the user BEFORE committing.

## Commands

```bash
python manage.py runserver | migrate | makemigrations | createsuperuser
pytest                                   # every step must end green
python manage.py spectacular --file openapi.yaml --validate --fail-on-warn
```

## Structure

`config/settings/{base,dev,prod}.py` · `config/api_urls.py` (everything under `/api/v1/`) ·
`apps/{core,accounts,catalog,cart,orders,payments,reviews,content}` (built step by step) ·
`docs/API_CONTRACT.md` · `openapi.yaml`

## API contract

Canonical: `docs/API_CONTRACT.md`. Generated schema: `openapi.yaml` and `/api/docs/`. Change the contract doc and the
schema together, and never diverge from what the frontend calls without the user's approval.

## Conventions

- Every response uses the envelope `{success, message, data}`; errors are
  `{success:false, message, error (string), errors (string[]), field_errors?}`. Views return `Response(data)` or
  `api_response(data, message=...)`; never hand-build the envelope (renderer + `envelope_exception_handler` do it).
- Money: `DecimalField(12, 2)` and `apps/core/money.py` only, never `float`. On the wire money is a JSON number
  (`COERCE_DECIMAL_TO_STRING=False`), because the frontend does arithmetic and `.toFixed()` on it.
- Stock/orders: only through `orders.services.place_order()` inside `transaction.atomic()` with `select_for_update()`
  (lock variants in id order). Order status changes only through the transition map in `orders/state.py`, always
  writing `OrderStatusHistory`.
- Status codes matter to the frontend: bad OTP/validation/out-of-stock = 400; 401 ONLY for missing/expired/invalid
  tokens (a 401 makes the frontend try to refresh, then log the user out).
- `apps/accounts` (and `core`) must not import shop apps (catalog/cart/orders...): this base is reused for other
  projects. Cross-app hooks go through signals, e.g. `accounts.signals.guest_data_received` (guest cart/favorites
  sent at sign-in; the cart/wishlist apps connect a receiver). Receivers run with `send_robust`.
- A DRF view with `authentication_classes = []` must define `get_authenticate_header()`, otherwise DRF turns every 401
  into a 403 (see `PublicAuthView`). Public auth views ignore the Authorization header on purpose: the frontend sends
  its stale access token to refresh/logout.
- OTP delivery is pluggable via `OTP_BACKEND` (`apps/accounts/otp/backends.py`). Only `ConsoleOTPBackend` may print
  a code, and prod has no default backend.
- Both `/x` and `/x/` must resolve with no redirect: register routes with `apps.core.urls.dual_path`. `APPEND_SLASH=False`.
- Views stay thin, logic lives in `services.py`; serializers validate; permissions per view. The default permission is
  `IsAuthenticated`, so public endpoints must say `permission_classes = [AllowAny]`.
- Uploads: validate type and size. HTML fields are sanitized with nh3 on write. Never log OTPs; mask phone numbers.
- Tests with pytest-django. Every step ends with `pytest` green and `spectacular --validate --fail-on-warn` clean.
