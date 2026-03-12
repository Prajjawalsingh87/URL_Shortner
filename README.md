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
git clone https://github.com/yourusername/url-shortener.git
cd url-shortener
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

## ☁️ Free-Tier Deployment on Railway

### Step 1: Push to GitHub
```bash
git init && git add . && git commit -m "Initial commit"
git push origin main
```

### Step 2: Deploy Backend on Railway
1. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
2. Select your repository
3. Railway will auto-detect the Dockerfile in `backend/`
4. Add a **PostgreSQL** plugin and a **Redis** plugin from Railway's dashboard
5. Set environment variables in Railway:
   - `DATABASE_URL` — auto-provided by Railway's PostgreSQL plugin
   - `REDIS_URL` — auto-provided by Railway's Redis plugin
   - `BASE_URL` — your Railway public domain (e.g. `https://app.up.railway.app`)
   - `ALLOWED_ORIGINS` — your frontend URL

### Step 3: Deploy Frontend on Vercel / Netlify
1. Move `frontend/` to a separate repo or configure your host to serve it
2. Update `BASE_URL` in `script.js` to your Railway backend URL
3. Deploy with `vercel --prod` or drag-drop to Netlify

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
