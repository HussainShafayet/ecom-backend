# Starting a new project from this template

This repo started as the backend of one project (GoCart) and is meant to be reused. The reusable base is
**`config/` + `apps/core` + `apps/accounts`**. Everything shop-specific (catalog, cart, orders, payments, reviews,
content) is added on top, later, and is not part of the base. The base is frozen as the git tag `template-base-v1`.

## 1. Copy the base

```bash
git clone --branch template-base-v1 <url-of-this-repo> my-project-backend
cd my-project-backend
rm -rf .git && git init -b main        # fresh history for the new project
```

## 2. Rename what is project-specific

Find the spots with `grep -rniE "gocart|ecom" --exclude-dir=venv --exclude-dir=.git .`.

| Where | Change |
|---|---|
| `CLAUDE.md` | title, first paragraph, everything tagged **[PROJECT]**, `<backend-dir>` |
| `README.md` | title/intro, database and role name (`gocart`) |
| `.env.example` | `DATABASE_URL` role/db name, `FRONTEND_URL`, `CORS_ALLOWED_ORIGINS` |
| `config/settings/base.py` | `SPECTACULAR_SETTINGS` `TITLE` / `DESCRIPTION` |
| `docs/API_CONTRACT.md` | delete; write the new project's contract (see step 6) |
| `openapi.yaml` | regenerate: `python manage.py spectacular --file openapi.yaml --validate --fail-on-warn` |

## 3. Decide what the new frontend needs (two choices baked into the base)

Both were dictated by the GoCart frontend, so check them against the new one first.

**a) Response envelope** `{success, message, data}` / errors `{success:false, message, error, errors[]}`.
It lives only in `apps/core/{renderers,errors,exceptions,schema}.py` (and their tests). If the new frontend expects
plain DRF output or another shape, change those four files; nothing else knows about the envelope.

**b) Phone number + OTP login** (`apps/accounts`, no customer passwords). If that fits, keep it. If the project needs
email + password (or social login), replace `apps/accounts`: the user model, manager, validators and the OTP code.
`AUTH_USER_MODEL` must be settled **before the first `migrate`** of the new project, so delete
`apps/accounts/migrations/` and regenerate them on a fresh database (never on one that holds data).
Also GoCart-specific: `verify-otp` accepts the guest's `cart` / `favorite` lists and emits the
`guest_data_received` signal. Drop them from `VerifyOTPSerializer` / `services.complete_sign_in` if not needed.

## 4. Bootstrap

Follow README.md: create the PostgreSQL role/database, `python3 -m venv venv`, `pip install -r requirements-dev.txt`,
`cp .env.example .env`, `migrate`, `createsuperuser`, `pytest` (must be green before you add anything).

## 5. Add the project's apps

1. `mkdir apps/<name> && python manage.py startapp <name> apps/<name>`, set `name = "apps.<name>"` in its `apps.py`.
2. Add it to `INSTALLED_APPS`, include its urls in `config/api_urls.py` **above** the catch-all route.
3. Register routes with `apps.core.urls.dual_path` when the frontend calls both `/x` and `/x/`.
4. Views return `Response(data)` / `api_response(...)`; public views set `permission_classes = [AllowAny]`
   (the default is `IsAuthenticated`); annotate with `extend_schema`.
5. Money is `DecimalField(12, 2)` via `apps/core/money.py`. `accounts` and `core` never import project apps: connect
   to `accounts.signals` instead.
6. Tests for every endpoint; update the contract and `openapi.yaml`.

## 6. The workflow that produced this repo (works well with Claude Code)

1. Give Claude the frontend folder. It reads every API call, type, form rule and flow, and lists what is unclear.
2. Answer the questions; Claude drafts the API contract (endpoints, shapes, errors, pagination) and the design
   (apps, ER diagram, order/stock rules, auth, media, settings).
3. Implement in small steps, one branch and one pull request per step, each step ending with tests, schema validation
   and a live smoke test before merging.

## Pulling later improvements from the template

```bash
git remote add template <url-of-this-repo>
git fetch template --tags
git cherry-pick <commit>          # pick the fixes/features you want; check tags with `git tag -l "template-*"`
```
