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
| `ALLOWED_ORIGINS`   | CORS allowed frontend origins        | `http://localhost:3000,...`    |

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

### GET `/{short_code}` — Redirect

```bash
curl -L http://localhost:8000/aB3kX9z
# → 302 redirect to original URL
```

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
  "recent_clicks": [...],
  "top_user_agents": [...],
  "top_ips": [...]
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
  is_active    BOOLEAN DEFAULT TRUE
);

-- Clicks analytics table
CREATE TABLE clicks (
  id          SERIAL PRIMARY KEY,
  short_code  VARCHAR(20) REFERENCES urls(short_code) ON DELETE CASCADE,
  timestamp   TIMESTAMP DEFAULT NOW(),
  ip_address  VARCHAR(45),
  user_agent  TEXT
);
```

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
  `REDIS_URL` the cache is simply off. Deploy with `cd backend && vercel deploy --prod`.
- **Frontend** (`frontend/`) is the Vercel project `snaplink`. Its `vercel.json` proxies `/api/*`
  to the backend and forwards short codes (`/AbC123`) to the backend's redirect endpoint, so short
  links live on the frontend's domain.
