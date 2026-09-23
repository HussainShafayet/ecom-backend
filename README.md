# GoCart Backend

Django + Django REST Framework API for the GoCart React storefront (`../ecom`). PostgreSQL, JWT (simplejwt),
OpenAPI via drf-spectacular. The API shape is dictated by the frontend, see [docs/API_CONTRACT.md](docs/API_CONTRACT.md).

No Docker: a Python virtualenv plus a locally installed PostgreSQL.

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
```

## Layout

```
config/            settings/{base,dev,prod}.py, urls.py, api_urls.py (everything under /api/v1/)
apps/core/         response envelope, error handling, pagination, money helpers, URL helper, health check
apps/accounts/     custom User (phone identity)
docs/API_CONTRACT.md   canonical API contract (what the frontend calls)
openapi.yaml       generated schema (keep in sync: see command above)
```

More apps (`catalog`, `cart`, `orders`, `payments`, `reviews`, `content`) are added step by step.

## Settings

`DJANGO_SETTINGS_MODULE` and everything else come from `.env` (see `.env.example`). `config.settings.dev` is the
default for `manage.py`; deployed environments set `DJANGO_SETTINGS_MODULE=config.settings.prod`.

## Troubleshooting

- `password authentication failed for user "gocart"`: role/password differs from `DATABASE_URL`, or you used
  `localhost` instead of `127.0.0.1`.
- `permission denied to create database` when running pytest: the role lacks `CREATEDB`
  (`sudo -u postgres psql -c "ALTER ROLE gocart CREATEDB"`).
- `connection refused`: PostgreSQL isn't running (`sudo systemctl start postgresql`).
