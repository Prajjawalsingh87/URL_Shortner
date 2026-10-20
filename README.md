# SnapLink — Production URL Shortener

<div align="center">

**A scalable, production-ready URL shortener built with FastAPI · PostgreSQL · Redis**

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green?logo=fastapi)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue?logo=postgresql)
![Redis](https://img.shields.io/badge/Redis-7-red?logo=redis)
![Docker](https://img.shields.io/badge/Docker-Compose-blue?logo=docker)

</div>

---

## 📖 Project Overview

SnapLink transforms long URLs into compact, shareable links using **Base62 encoding**. Every redirect is cached in Redis for sub-millisecond lookups, while PostgreSQL stores all analytics data including per-click IP addresses, timestamps, and user agents.

### Features

- **Short links** with optional custom alias and expiry; the destination is checked for reachability first.
- **QR code for every link**, generated in the browser ([qrcode-generator](https://www.npmjs.com/package/qrcode-generator)) on the result card and from the recent-links list, with **Download PNG** (1024 px).
- **Link preview**: when a link is created the backend fetches the page's `<title>`, `og:image` and `og:description` and the UI shows a small preview card.
- **Bulk shorten**: paste up to 20 URLs (one per line) and get a list back with **Copy all** and **Download CSV**. Each line succeeds or fails on its own.
- **Click analytics**: clicks per day plus top **countries**, **devices**, **browsers**, **operating systems** and **referrers**, and a recent-clicks table.
- **Recent links** saved in the browser, with search and JSON export.
- **Accounts + "My links" dashboard**: optional email/password sign-up. Links created while logged in belong to you and show up in the dashboard (any device) with click counts, created/expiry dates and search; change or remove a link's expiry, or delete it. Anonymous shortening keeps working.
- **Password-protected links**: set an optional password when creating a link; visitors get a small password page first (wrong guesses are rate-limited) and the click is recorded once they get in. Only the owner can see a protected link's destination and stats.

## 🌐 Live Demo

- Frontend: https://snaplink-ten-eosin.vercel.app
- Backend API: https://snaplink-api-six.vercel.app (Vercel serverless + Neon Postgres)
- API Docs: https://snaplink-api-six.vercel.app/docs

### Architecture

```
User → Nginx (frontend) → FastAPI Backend → Redis Cache (hit?)
                                        ↓ (miss)
                                   PostgreSQL
```

---

## 🗂️ Folder Structure

```
url-shortener/
│
├── backend/
│   ├── app/
│   │   ├── __init__.py       # Python package init
│   │   ├── main.py           # FastAPI app, CORS, lifespan hooks
│   │   ├── database.py       # SQLAlchemy engine + session
│   │   ├── models.py         # ORM models (URLs, Clicks)
│   │   ├── schemas.py        # Pydantic request/response schemas
│   │   ├── routes.py         # All API endpoints
│   │   ├── utils.py          # Base62 encoding, URL validation
│   │   └── cache.py          # Redis async client wrapper
│   ├── requirements.txt
│   └── Dockerfile            # Multi-stage production build
│
├── frontend/
│   ├── index.html            # Main UI
│   ├── style.css             # Dark-mode premium design
│   └── script.js             # API calls + analytics charts
│
├── .env.example              # Environment variable template
├── docker-compose.yml        # Full stack orchestration
└── README.md
```

---

## ⚙️ Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable            | Description                          | Default                        |
|---------------------|--------------------------------------|--------------------------------|
| `POSTGRES_DB`       | PostgreSQL database name             | `urlshortener`                 |
| `POSTGRES_USER`     | PostgreSQL username                  | `postgres`                     |
| `POSTGRES_PASSWORD` | PostgreSQL password                  | *(required)*                   |
| `REDIS_PASSWORD`    | Redis server password                | *(required)*                   |
| `CACHE_TTL_SECONDS` | Redis cache TTL                      | `3600`                         |
| `BASE_URL`          | Public backend URL for short links   | `http://localhost:8000`        |
| `ALLOWED_ORIGINS`   | CORS allowed frontend origins (also the origins allowed to make logged-in changes) | `http://localhost:3000,...` |
| `JWT_SECRET`        | Signs session cookies. **Required** on Vercel (set per environment with `vercel env add JWT_SECRET production` / `preview`); random per process in local dev | *(required in prod)* |
| `COOKIE_SECURE`     | `0` only for plain-http local dev    | `1`                            |
| `BCRYPT_ROUNDS`     | bcrypt cost factor                   | `12`                           |

---

## 🚀 Local Development

### Prerequisites
- Docker Desktop (or Docker Engine + Compose v2)
- Git

### 1. Clone the repository
```bash
git clone https://github.com/Prajjawalsingh87/URL_Shortner.git
cd URL_Shortner
```

### 2. Set up environment variables
```bash
cp .env.example .env
# Edit .env and set your POSTGRES_PASSWORD and REDIS_PASSWORD
nano .env
```

### 3. Start the stack
```bash
docker compose up --build
```

### 4. Access the services
| Service     | URL                            |
|-------------|--------------------------------|
| Frontend    | http://localhost:3000          |
| Backend API | http://localhost:8000          |
| API Docs    | http://localhost:8000/docs     |
| ReDoc       | http://localhost:8000/redoc    |

---

## 📡 API Endpoints

### POST `/shorten` — Create a Short URL

```bash
curl -X POST http://localhost:8000/shorten \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.example.com/very/long/path?with=query&params=here",
    "custom_code": "my-link",
    "expires_in_days": 30
  }'
```

**Response:**
```json
{
  "short_url": "http://localhost:8000/my-link",
  "short_code": "my-link",
  "original_url": "https://www.example.com/...",
  "created_at": "2026-03-11T07:59:08Z",
  "expires_at": "2026-04-10T07:59:08Z"
}
```

---

The response also carries the link preview fields `title`, `description` and `image_url`
(each `null` when the page has none or could not be fetched).

---

### POST `/shorten/bulk` — Shorten up to 20 URLs

```bash
curl -X POST http://localhost:8000/shorten/bulk \
  -H "Content-Type: application/json" \
  -d '{"urls": ["https://example.com", "python.org", "not a url"], "expires_in_days": 30}'
```

Blank lines are ignored, a missing scheme becomes `https://`, and more than 20 URLs is a `422`.
URLs are checked concurrently (10 at a time) and each one reuses the single `/shorten` logic:

```json
{
  "total": 3, "succeeded": 2, "failed": 1,
  "results": [
    { "input": "https://example.com", "ok": true, "error": null,
      "link": { "short_url": "https://snaplink-ten-eosin.vercel.app/68g9xMH", "short_code": "68g9xMH", "title": "Example Domain", "...": "..." } },
    { "input": "python.org", "ok": true, "error": null, "link": { "...": "..." } },
    { "input": "not a url", "ok": false, "error": "Invalid URL format. Ensure it starts with http:// or https://", "link": null }
  ]
}
```

---

### Accounts

Sessions are a signed JWT in an **httpOnly, Secure, SameSite=Lax** cookie (`snaplink_session`,
7 days). Browsers must send `credentials: "include"`; the frontend reaches the API through its own
`/api` proxy, so the cookie is first-party.

| Method | Path | Notes |
|--------|------|-------|
| `POST` | `/auth/signup` | `{"email", "password"}` (8–72 bytes). 409 if the email exists. Logs you in. |
| `POST` | `/auth/login` | 401 on a wrong email/password; 429 after 5 failures per email or 20 per IP in 15 min |
| `POST` | `/auth/logout` | Clears the cookie |
| `GET` | `/auth/me` | The current user, or 401 |
| `GET` | `/me/links?q=` | Your links with `total_clicks`, `expires_at`, `expired`, `password_protected`; `q` searches URL, title and code |
| `PATCH` | `/links/{code}` | `{"expires_in_days": 7}` or `{"expires_in_days": null}` to never expire. Owner only (403 otherwise) |
| `DELETE` | `/links/{code}` | Deletes the link and its clicks. Owner only |

`POST /shorten` and `POST /shorten/bulk` attach new links to the logged-in user (if any) and accept
an optional `"password"` (4–72 bytes) on `/shorten` for a protected link. The response includes
`password_protected` and `owned`.

---

### GET `/{short_code}` — Redirect

```bash
curl -L http://localhost:8000/aB3kX9z
# → 302 redirect to original URL
```

For a **password-protected** link this returns a small password page instead (no scripts,
strict CSP, `no-store`); the page POSTs to `/{short_code}`, which answers `401` with the page again
on a wrong password, `429` after 5 wrong tries per link and IP in 15 minutes, and `303` to the
destination on success (the click is recorded then). `/preview` and `/analytics` return `403` for
protected links unless you are the owner.

Each redirect records a click with the visitor IP (first `X-Forwarded-For` hop), user agent,
**country** (from Vercel's `x-vercel-ip-country` header; blank outside Vercel, no paid geo-IP
lookups), **device** (desktop / mobile / tablet / bot), **browser**, **OS** and **referrer host**.

---

### GET `/preview/{short_code}` — Preview Without Redirect

```bash
curl http://localhost:8000/preview/aB3kX9z
```

**Response:**
```json
{
  "short_code": "aB3kX9z",
  "original_url": "https://www.youtube.com/watch?v=...",
  "created_at": "2026-03-11T07:59:08Z",
  "total_clicks": 42,
  "expires_at": null
}
```

---

### GET `/analytics/{short_code}` — Click Analytics

```bash
curl http://localhost:8000/analytics/aB3kX9z
```

**Response:**
```json
{
  "short_code": "aB3kX9z",
  "original_url": "https://...",
  "total_clicks": 42,
  "created_at": "2026-03-11T07:59:08Z",
  "expires_at": null,
  "clicks_per_day": [
    { "date": "2026-03-11", "count": 42 }
  ],
  "recent_clicks": [
    { "timestamp": "...", "ip_address": "...", "user_agent": "...",
      "country": "IN", "device": "mobile", "browser": "Safari", "os": "iOS", "referrer": "twitter.com" }
  ],
  "top_user_agents": [...],
  "top_ips": [...],
  "top_countries": [{ "name": "IN", "count": 30 }, { "name": "US", "count": 12 }],
  "top_devices":   [{ "name": "mobile", "count": 25 }, { "name": "desktop", "count": 17 }],
  "top_browsers":  [{ "name": "Chrome", "count": 28 }],
  "top_os":        [{ "name": "Android", "count": 20 }],
  "top_referrers": [{ "name": "Direct", "count": 22 }, { "name": "twitter.com", "count": 9 }],
  "title": "Page title", "description": "...", "image_url": "https://..."
}
```

---

### GET `/health` — Health Check

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "healthy",
  "database": "healthy",
  "cache": "healthy"
}
```

---

## 🗄️ Database Schema

```sql
-- URLs table
CREATE TABLE urls (
  id          SERIAL PRIMARY KEY,
  original_url TEXT NOT NULL,
  short_code   VARCHAR(20) UNIQUE NOT NULL,
  custom_code  BOOLEAN DEFAULT FALSE,
  created_at   TIMESTAMP DEFAULT NOW(),
  expires_at   TIMESTAMP,
  is_active    BOOLEAN DEFAULT TRUE,
  title        TEXT,          -- link preview
  description  TEXT,
  image_url    TEXT,
  owner_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,  -- NULL = anonymous
  password_hash TEXT                                              -- bcrypt; NULL = not protected
);

-- Accounts
CREATE TABLE users (
  id            SERIAL PRIMARY KEY,
  email         VARCHAR(254) UNIQUE NOT NULL,   -- lower-cased
  password_hash TEXT NOT NULL,                  -- bcrypt
  created_at    TIMESTAMP DEFAULT NOW()
);

-- Failed logins / link-password guesses / sign-ups, for rate limiting
-- (in the database because serverless instances share no memory)
CREATE TABLE rate_events (
  id         SERIAL PRIMARY KEY,
  bucket     VARCHAR(20) NOT NULL,
  key        VARCHAR(300) NOT NULL,
  created_at TIMESTAMP NOT NULL
);

-- Clicks analytics table
CREATE TABLE clicks (
  id          SERIAL PRIMARY KEY,
  short_code  VARCHAR(20) REFERENCES urls(short_code) ON DELETE CASCADE,
  timestamp   TIMESTAMP DEFAULT NOW(),
  ip_address  VARCHAR(45),
  user_agent  TEXT,
  country     VARCHAR(8),     -- ISO code from x-vercel-ip-country
  device      VARCHAR(20),
  browser     VARCHAR(40),
  os          VARCHAR(40),
  referrer    VARCHAR(255)    -- referring host only
);
```

There are no migrations: tables are created on first use, and columns added after the first
release are added in place by `ensure_tables()` (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` on
Postgres; a column check on SQLite for local dev). Older clicks without device/browser/OS are
classified from their stored user agent when analytics are read.

---

## ☁️ Deployment on Render

### Step 1: Push to GitHub
```bash
git init && git add . && git commit -m "Initial commit"
git push origin main
```

### Step 2: Deploy Backend on Render
1. Go to [render.com](https://render.com) → New Web Service
2. Select your repository
3. Set `Language` to `Docker`
4. Set `Root Directory` to `backend`
5. Set backend environment variables in Render:
   - `DATABASE_URL` — your PostgreSQL connection string
   - `REDIS_URL` — your Redis connection string
   - `CACHE_TTL_SECONDS` — e.g. `3600`
   - `BASE_URL` — your Render backend domain (e.g. `https://url-shortner-xzz7.onrender.com`)
   - `ALLOWED_ORIGINS` — your frontend URL

### Step 3: Deploy Frontend on Render
1. Create a new **Static Site** in Render
2. Select the same repository
3. Set `Root Directory` to `frontend`
4. Leave `Build Command` empty
5. Set `Publish Directory` to `.`
6. Redeploy the backend after adding the frontend Render domain to `ALLOWED_ORIGINS`

---

## 🏗️ Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Base62 encoding** | Compact, URL-safe codes using 0-9, a-z, A-Z |
| **Redis cache** | Avoids DB hit on every redirect — critical for high traffic |
| **Duplicate prevention** | Same URL returns existing short code (saves DB rows) |
| **Hash collision handling** | Suffix-increment (`code1`, `code2`) resolves collisions |
| **302 redirect** | Temporary redirect; prevents browser caching of moved links |
| **Multi-stage Dockerfile** | Smaller, more secure production image |
| **Non-root container user** | Follows Docker security best practices |

---

## 🔒 Security Notes

- All credentials are loaded from environment variables — never hardcoded
- CORS is explicitly configured to only allow trusted origins
- Container runs as a non-root user
- URL reachability is validated before shortening to prevent abuse
- The link-preview fetcher only follows `http`/`https`, resolves every hop (redirects are followed
  manually, at most 3) and refuses loopback, private, link-local and other non-public addresses
  (SSRF guard), uses a 4 s timeout and reads at most 512 KB of HTML; failures never block shortening
- Bulk CSV export neutralises spreadsheet formulas (cells starting with `=`, `+`, `-`, `@`)
- Passwords (account and link) are hashed with **bcrypt**; login and link-unlock attempts are
  rate-limited in the database; unknown emails cost the same bcrypt time as wrong passwords
- **CSRF**: the session cookie is `SameSite=Lax` and httpOnly, and every POST/PUT/PATCH/DELETE that
  carries it must send an `Origin` (or `Referer`) from `ALLOWED_ORIGINS`/`BASE_URL`, otherwise 403.
  Requests without the cookie (anonymous API use) are unaffected
- `JWT_SECRET` lives only in Vercel environment variables; without it on Vercel, accounts are
  disabled (503) rather than falling back to an insecure key
- The password page sends `Content-Security-Policy: default-src 'none'`, `frame-ancestors 'none'`
  and `Referrer-Policy: same-origin`, so the destination never learns the short link page
- `.env` is gitignored — never commit real secrets

---

## 📦 Tech Stack

| Layer | Technology |
|-------|-----------|
| Web Framework | FastAPI 0.111 |
| ASGI Server | Uvicorn |
| Database ORM | SQLAlchemy 2.0 |
| Database | PostgreSQL 16 |
| Cache | Redis 7 |
| HTTP Client | httpx (async) |
| Data Validation | Pydantic 2 |
| Frontend | Vanilla HTML/CSS/JS |
| Containerization | Docker + Docker Compose |
| Reverse Proxy | Nginx |


## October 2026 improvements

Search recent links by URL or short code and export local link history as JSON. These controls do not delete server-side links. The frontend shares the indigo/slate visual language.


## Vercel frontend

Run `vercel link --project snaplink` and `vercel deploy` from `frontend/`.
The static frontend has no build step. On `*.vercel.app`, its `/api/*` requests
are proxied to the existing Render backend through `frontend/vercel.json`.
This avoids needing a new browser CORS origin. Custom domains must set the
`snaplink-api` meta tag appropriately or extend `resolveApiBase`.

PostgreSQL, Redis and the FastAPI backend remain separate services on Render.
Deploying the frontend does not provision a database or migrate backend data.

## Deploying on Vercel (current setup)

- **Backend** (`backend/`) runs as a Python serverless function on the Vercel project `snaplink-api`
  (`backend/api/index.py` + `backend/vercel.json`). Database: **Neon Postgres** from the Vercel
  Marketplace, which sets `DATABASE_URL` automatically. Also set `BASE_URL`
  (`https://snaplink-ten-eosin.vercel.app`) and `ALLOWED_ORIGINS`. Redis is optional: without
  `REDIS_URL` the cache is simply off. The project is connected to this GitHub repo with Root
  Directory `backend`, so every push to `main` deploys to production and every PR gets a preview.
- **Frontend** (`frontend/`) is the Vercel project `snaplink`. Its `vercel.json` proxies `/api/*`
  to the backend and forwards short codes (`/AbC123`) to the backend's redirect endpoint, so short
  links live on the frontend's domain. It is also git-connected (Root Directory `frontend`) and
  deploys on push to `main`.

### Local development without Docker

```bash
cd backend
VERCEL=1 COOKIE_SECURE=0 DATABASE_URL=sqlite:////tmp/snaplink.db ../.venv/bin/uvicorn app.main:app --port 8000
# in another shell
cd frontend && python3 -m http.server 5500
# open http://127.0.0.1:5500/?api=http://127.0.0.1:8000
```

### Tests

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest -q
```

The suite (`backend/tests/`) covers sign-up/login/logout, login rate limiting, tampered sessions,
the CSRF origin check, link ownership (dashboard isolation, edit expiry, delete), and protected
links (password page, wrong/right password, rate limiting, owner-only stats). It runs on SQLite with
network calls stubbed, and in GitHub Actions on every PR that touches `backend/`.
