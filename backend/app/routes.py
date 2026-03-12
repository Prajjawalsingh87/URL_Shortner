"""
routes.py - All API route definitions for the URL shortener.

Endpoints:
  POST /shorten            - Create a shortened URL
  GET  /{short_code}       - Redirect to original URL
  GET  /preview/{short_code} - Preview destination without redirect
  GET  /analytics/{short_code} - Get click analytics
  GET  /health             - Health check
"""

import os
import logging
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from .database import get_db
from .models import URL, Click
from .schemas import (
    ShortenRequest, ShortenResponse, PreviewResponse,
    AnalyticsResponse, HealthResponse, DailyClicks, ClickRecord
)
from .utils import (
    generate_short_code, is_valid_url, is_url_reachable,
    calculate_expiry, is_expired
)
from .cache import get_cached_url, set_cached_url, delete_cached_url, is_redis_healthy

logger = logging.getLogger(__name__)
router = APIRouter()

# Base URL for constructing short links (from env or default)
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


# ──────────────────────────────────────────────
# POST /shorten
# ──────────────────────────────────────────────
@router.post("/shorten", response_model=ShortenResponse, status_code=201)
async def shorten_url(payload: ShortenRequest, db: Session = Depends(get_db)):
    """
    Accept a long URL, validate it, generate a Base62 short code,
    store in PostgreSQL, and return the shortened URL.
    """
    url = payload.url.strip()

    # 1. Validate URL format
    if not is_valid_url(url):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid URL format. Ensure it starts with http:// or https://"
        )

    # 2. Check if URL is reachable (non-blocking, timeout=5s)
    reachable, error_msg = await is_url_reachable(url)
    if not reachable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"URL is not reachable: {error_msg}"
        )

    # 3. Handle custom short code
    if payload.custom_code:
        existing = db.query(URL).filter(URL.short_code == payload.custom_code).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Custom code '{payload.custom_code}' is already taken."
            )
        short_code = payload.custom_code
        is_custom = True
    else:
        # 4. Generate Base62 short code; handle hash collisions
        short_code = generate_short_code(url)
        is_custom = False

        # Check if same original_url already exists (return existing entry)
        existing = db.query(URL).filter(URL.original_url == url).first()
        if existing and existing.is_active:
            if not is_expired(existing.expires_at):
                # Return the existing shortened URL instead of creating a duplicate
                short_url = f"{BASE_URL}/{existing.short_code}"
                return ShortenResponse(
                    short_url=short_url,
                    short_code=existing.short_code,
                    original_url=existing.original_url,
                    created_at=existing.created_at,
                    expires_at=existing.expires_at,
                )

        # Handle hash collision: append suffix if code exists for a different URL
        collision_count = 0
        base_code = short_code
        while db.query(URL).filter(URL.short_code == short_code).first():
            collision_count += 1
            short_code = f"{base_code}{collision_count}"

    # 5. Calculate expiry
    expires_at = calculate_expiry(payload.expires_in_days)

    # 6. Persist to PostgreSQL
    db_url = URL(
        original_url=url,
        short_code=short_code,
        custom_code=is_custom,
        expires_at=expires_at,
    )
    db.add(db_url)
    db.commit()
    db.refresh(db_url)

    # 7. Pre-warm Redis cache
    await set_cached_url(short_code, url)

    short_url = f"{BASE_URL}/{short_code}"
    logger.info(f"Created short URL: {short_url} -> {url}")

    return ShortenResponse(
        short_url=short_url,
        short_code=short_code,
        original_url=url,
        created_at=db_url.created_at,
        expires_at=db_url.expires_at,
    )


# ──────────────────────────────────────────────
# GET /health
# ──────────────────────────────────────────────
@router.get("/health", response_model=HealthResponse)
async def health_check(db: Session = Depends(get_db)):
    """
    System health check — verifies database and Redis connectivity.
    """
    # Check DB
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        logger.error(f"DB health check failed: {e}")
        db_status = "unhealthy"

    # Check Redis
    redis_ok = await is_redis_healthy()
    cache_status = "healthy" if redis_ok else "unavailable"

    overall = "healthy" if db_status == "healthy" else "degraded"

    return HealthResponse(
        status=overall,
        database=db_status,
        cache=cache_status,
    )


# ──────────────────────────────────────────────
# GET /preview/{short_code}
# ──────────────────────────────────────────────
@router.get("/preview/{short_code}", response_model=PreviewResponse)
async def preview_url(short_code: str, db: Session = Depends(get_db)):
    """
    Show the destination URL and basic stats without performing a redirect.
    Useful for users to verify before visiting.
    """
    db_url = db.query(URL).filter(
        URL.short_code == short_code,
        URL.is_active == True
    ).first()

    if not db_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Short code '{short_code}' not found."
        )

    if is_expired(db_url.expires_at):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This shortened URL has expired."
        )

    total_clicks = db.query(Click).filter(Click.short_code == short_code).count()

    return PreviewResponse(
        short_code=short_code,
        original_url=db_url.original_url,
        created_at=db_url.created_at,
        total_clicks=total_clicks,
        expires_at=db_url.expires_at,
    )


# ──────────────────────────────────────────────
# GET /analytics/{short_code}
# ──────────────────────────────────────────────
@router.get("/analytics/{short_code}", response_model=AnalyticsResponse)
async def get_analytics(short_code: str, db: Session = Depends(get_db)):
    """
    Return detailed click analytics for a short code.
    Includes total clicks, daily breakdown, top IPs, and user agents.
    """
    db_url = db.query(URL).filter(URL.short_code == short_code).first()

    if not db_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Short code '{short_code}' not found."
        )

    # Fetch all clicks
    clicks = db.query(Click).filter(Click.short_code == short_code).all()

    # Clicks per day
    daily: dict[str, int] = defaultdict(int)
    for click in clicks:
        date_str = click.timestamp.strftime("%Y-%m-%d")
        daily[date_str] += 1

    clicks_per_day = [
        DailyClicks(date=date, count=count)
        for date, count in sorted(daily.items())
    ]

    # Top user agents
    ua_counter = Counter(c.user_agent for c in clicks if c.user_agent)
    top_user_agents = [
        {"user_agent": ua, "count": count}
        for ua, count in ua_counter.most_common(5)
    ]

    # Top IPs
    ip_counter = Counter(c.ip_address for c in clicks if c.ip_address)
    top_ips = [
        {"ip_address": ip, "count": count}
        for ip, count in ip_counter.most_common(5)
    ]

    # Recent 20 clicks
    recent = clicks[-20:][::-1]
    recent_clicks = [
        ClickRecord(
            timestamp=c.timestamp,
            ip_address=c.ip_address,
            user_agent=c.user_agent
        )
        for c in recent
    ]

    return AnalyticsResponse(
        short_code=short_code,
        original_url=db_url.original_url,
        total_clicks=len(clicks),
        created_at=db_url.created_at,
        expires_at=db_url.expires_at,
        clicks_per_day=clicks_per_day,
        recent_clicks=recent_clicks,
        top_user_agents=top_user_agents,
        top_ips=top_ips,
    )


# ──────────────────────────────────────────────
# GET /{short_code} — Redirect (DYNAMIC ROUTE AT END)
# ──────────────────────────────────────────────
@router.get("/{short_code}")
async def redirect_to_url(short_code: str, request: Request, db: Session = Depends(get_db)):
    """
    Redirect short code to the original URL.
    Checks Redis cache first; falls back to PostgreSQL.
    Records click analytics.
    """
    # Reserved routes — don't treat as short codes
    reserved = {"docs", "redoc", "openapi.json", "health", "shorten", "preview", "analytics", "favicon.ico"}
    if short_code in reserved:
        raise HTTPException(status_code=404, detail="Not found")

    # 1. Check Redis cache first
    original_url = await get_cached_url(short_code)

    # 2. Cache miss — query PostgreSQL
    if not original_url:
        db_url = db.query(URL).filter(
            URL.short_code == short_code,
            URL.is_active == True
        ).first()

        if not db_url:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Short code '{short_code}' not found or has been deactivated."
            )

        # Check expiry
        if is_expired(db_url.expires_at):
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="This shortened URL has expired."
            )

        original_url = db_url.original_url
        # Cache for future requests
        await set_cached_url(short_code, original_url)

    # 3. Record click analytics (async, non-blocking)
    client_ip = request.client.host if request.client else "unknown"
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()

    user_agent = request.headers.get("User-Agent", "unknown")

    click = Click(
        short_code=short_code,
        ip_address=client_ip,
        user_agent=user_agent,
    )
    db.add(click)
    db.commit()

    # 4. Redirect with 302 (temporary redirect; use 301 for permanent)
    return RedirectResponse(url=original_url, status_code=302)
