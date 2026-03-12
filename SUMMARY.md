# SnapLink Project Summary

## Project Overview
SnapLink is a production-ready URL shortener built with FastAPI, PostgreSQL, and Redis. It transforms long URLs into compact, shareable links using Base62 encoding and provides comprehensive click analytics.

## Key Features
- **URL Shortening**: Generates unique, compact short codes using Base62 encoding.
- **Custom Short Codes**: Allows users to specify their own short codes (e.g., `snap.link/my-product`).
- **High Performance Caching**: Uses Redis to cache redirects, ensuring sub-millisecond lookups and reducing database load.
- **Comprehensive Analytics**:
  - Total click counts.
  - Clicks per day (historical data).
  - Geographical data (IP addresses).
  - Device/Browser data (User Agents).
  - Recent click history.
- **Link Expiration**: Supports setting an expiration date for shortened links.
- **URL Validation**: Ensures the target URL is reachable and well-formatted before shortening.
- **Premium UI**: A sleek, dark-mode responsive frontend with analytics charts and a modern design.

## Technical Architecture
- **Backend**: FastAPI (Python 3.12)
- **Database**: PostgreSQL 16 (Relational storage for URLs and Clicks)
- **Cache**: Redis 7 (Speedy lookups for redirects)
- **ORM**: SQLAlchemy 2.0
- **Validation**: Pydantic 2
- **Containerization**: Docker & Docker Compose
- **Security**: Environment variable configuration, non-root Docker user, CORS protection.

## API Documentation
### 1. `POST /shorten`
Creates a shortened URL.
- **Input**: `url`, `custom_code` (optional), `expires_in_days` (optional).
- **Process**: Validates URL, generates Base62 code, saves to DB, warms Redis cache.

### 2. `GET /{short_code}`
Performs the redirect.
- **Process**: Checks Redis cache -> Checks PostgreSQL -> Records click analytics -> 302 Redirect.

### 3. `GET /preview/{short_code}`
Shows destination and stats without redirecting.

### 4. `GET /analytics/{short_code}`
Returns detailed analytics (daily clicks, top IPs, user agents).

### 5. `GET /health`
Verifies DB and Redis connectivity.

## Design Decisions
- **Base62 Encoding**: Uses `[a-zA-Z0-9]` for compact, URL-safe codes.
- **Redis First**: Redirects are served from Redis to minimize latency.
- **Non-blocking Analytics**: Click recording is handled within the request flow but designed for high throughput.
- **Multi-stage Docker build**: Optimizes image size and security for production deployment.
