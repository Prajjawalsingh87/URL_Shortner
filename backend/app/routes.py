"""
routes.py - All API route definitions for the URL shortener.

Endpoints:
  POST /shorten            - Create a shortened URL
  POST /shorten/bulk       - Shorten up to 20 URLs at once
  GET  /{short_code}       - Redirect to original URL (password page if protected)
  POST /{short_code}       - Unlock a password-protected link
  GET  /preview/{short_code} - Preview destination without redirect
  GET  /analytics/{short_code} - Get click analytics
  GET  /health             - Health check
"""

import os
import html
import asyncio
import logging
from urllib.parse import parse_qs
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from sqlalchemy.orm import Session

from .database import get_db
from .models import URL, Click, User
from .auth import (
    get_current_user, hash_password, verify_password, client_ip,
    is_rate_limited, record_event,
)
from .schemas import (
    ShortenRequest, ShortenResponse, PreviewResponse,
    AnalyticsResponse, HealthResponse, DailyClicks, ClickRecord,
    BulkShortenRequest, BulkShortenResponse, BulkItem,
)
from .utils import (
    generate_short_code, is_valid_url, is_url_reachable,
    calculate_expiry, is_expired,
    fetch_link_preview, parse_user_agent, referrer_host,
)
from .cache import get_cached_url, set_cached_url, delete_cached_url, is_redis_healthy

logger = logging.getLogger(__name__)
router = APIRouter()

# Base URL for constructing short links (from env or default)
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


# ──────────────────────────────────────────────
# Shared shorten logic (used by /shorten and /shorten/bulk)
# ──────────────────────────────────────────────
def _to_response(db_url: URL) -> ShortenResponse:
    return ShortenResponse(
        password_protected=db_url.is_protected,
        owned=db_url.owner_id is not None,
        short_url=f"{BASE_URL}/{db_url.short_code}",
        short_code=db_url.short_code,
        original_url=db_url.original_url,
        created_at=db_url.created_at,
        expires_at=db_url.expires_at,
        title=db_url.title,
        description=db_url.description,
        image_url=db_url.image_url,
    )


async def _check_url(url: str) -> dict:
    """
    Validate the URL, confirm it is reachable, and fetch its link preview.
    The reachability check and the preview fetch run concurrently; a failed
    preview never blocks shortening. Raises HTTPException when the URL is bad.
    """
    if not is_valid_url(url):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid URL format. Ensure it starts with http:// or https://"
        )

    (reachable, error_msg), preview = await asyncio.gather(
        is_url_reachable(url), fetch_link_preview(url)
    )
    if not reachable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"URL is not reachable: {error_msg}"
        )
    return preview


async def _store_url(
    db: Session,
    url: str,
    custom_code: Optional[str],
    expires_in_days: Optional[int],
    preview: dict,
    owner: Optional[User] = None,
    password: Optional[str] = None,
) -> ShortenResponse:
    """Persist a checked URL (or reuse an existing link for it) and return the response."""
    owner_id = owner.id if owner else None
    if custom_code:
        existing = db.query(URL).filter(URL.short_code == custom_code).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Custom code '{custom_code}' is already taken."
            )
        short_code = custom_code
        is_custom = True
    else:
        # Generate Base62 short code; handle hash collisions
        short_code = generate_short_code(url)
        is_custom = False

        # Same original_url already shortened by the same owner (or anonymously, for
        # anonymous requests) and not password-protected? Reuse it instead of a duplicate.
        existing = None if password else db.query(URL).filter(
            URL.original_url == url,
            URL.owner_id.is_(None) if owner_id is None else URL.owner_id == owner_id,
            URL.password_hash.is_(None),
        ).first()
        if existing and existing.is_active and not is_expired(existing.expires_at):
            # Backfill the preview for links created before previews existed
            if preview and not (existing.title or existing.image_url):
                existing.title = preview.get("title")
                existing.description = preview.get("description")
                existing.image_url = preview.get("image_url")
                db.commit()
                db.refresh(existing)
            return _to_response(existing)

        collision_count = 0
        base_code = short_code
        while db.query(URL).filter(URL.short_code == short_code).first():
            collision_count += 1
            short_code = f"{base_code}{collision_count}"

    db_url = URL(
        original_url=url,
        short_code=short_code,
        custom_code=is_custom,
        expires_at=calculate_expiry(expires_in_days),
        title=preview.get("title"),
        description=preview.get("description"),
        image_url=preview.get("image_url"),
        owner_id=owner_id,
        password_hash=hash_password(password) if password else None,
    )
    db.add(db_url)
    db.commit()
    db.refresh(db_url)

    # Pre-warm Redis cache (never for protected links: the cache path skips the password check)
    if not db_url.is_protected:
        await set_cached_url(short_code, url)
    logger.info(f"Created short URL: {BASE_URL}/{short_code} -> {url}")
    return _to_response(db_url)


# ──────────────────────────────────────────────
# POST /shorten
# ──────────────────────────────────────────────
@router.post("/shorten", response_model=ShortenResponse, status_code=201)
async def shorten_url(
    payload: ShortenRequest,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    """
    Accept a long URL, validate it, generate a Base62 short code,
    store it with a link preview, and return the shortened URL.
    """
    url = payload.url.strip()
    preview = await _check_url(url)
    return await _store_url(db, url, payload.custom_code, payload.expires_in_days, preview,
                            owner=user, password=payload.password)


# ──────────────────────────────────────────────
# POST /shorten/bulk
# ──────────────────────────────────────────────
BULK_CONCURRENCY = 10


@router.post("/shorten/bulk", response_model=BulkShortenResponse)
async def shorten_bulk(
    payload: BulkShortenRequest,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    """
    Shorten up to 20 URLs in one request. Each line succeeds or fails on its own;
    URLs are checked concurrently (at most 10 at a time) and stored in input order.
    """
    sem = asyncio.Semaphore(BULK_CONCURRENCY)

    async def check(raw: str):
        url = raw if raw.startswith(("http://", "https://")) else f"https://{raw}"
        async with sem:
            try:
                return url, await _check_url(url), None
            except HTTPException as e:
                return url, None, str(e.detail)

    checked = await asyncio.gather(*(check(u) for u in payload.urls))

    results: list[BulkItem] = []
    for raw, (url, preview, error) in zip(payload.urls, checked):
        if error:
            results.append(BulkItem(input=raw, ok=False, error=error))
            continue
        try:
            link = await _store_url(db, url, None, payload.expires_in_days, preview or {}, owner=user)
            results.append(BulkItem(input=raw, ok=True, link=link))
        except HTTPException as e:
            db.rollback()
            results.append(BulkItem(input=raw, ok=False, error=str(e.detail)))

    succeeded = sum(1 for r in results if r.ok)
    return BulkShortenResponse(
        total=len(results), succeeded=succeeded, failed=len(results) - succeeded, results=results
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
async def preview_url(
    short_code: str,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
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
    _hide_protected(db_url, user)

    total_clicks = db.query(Click).filter(Click.short_code == short_code).count()

    return PreviewResponse(
        short_code=short_code,
        original_url=db_url.original_url,
        created_at=db_url.created_at,
        total_clicks=total_clicks,
        expires_at=db_url.expires_at,
        title=db_url.title,
        description=db_url.description,
        image_url=db_url.image_url,
    )


# ──────────────────────────────────────────────
# GET /analytics/{short_code}
# ──────────────────────────────────────────────
@router.get("/analytics/{short_code}", response_model=AnalyticsResponse)
async def get_analytics(
    short_code: str,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
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
    _hide_protected(db_url, user)

    # Fetch all clicks
    clicks = db.query(Click).filter(Click.short_code == short_code).order_by(Click.timestamp, Click.id).all()

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

    # Device / browser / OS: clicks recorded before these columns existed are
    # classified from their stored user-agent on the fly.
    def ua_parts(c: Click) -> tuple[str, str, str]:
        if c.device or c.browser or c.os:
            return c.device or "unknown", c.browser or "Unknown", c.os or "Unknown"
        return parse_user_agent(c.user_agent)

    parsed = {c.id: ua_parts(c) for c in clicks}

    def top(values, n: int = 6) -> list[dict]:
        return [{"name": k, "count": v} for k, v in Counter(values).most_common(n)]

    top_countries = top((c.country for c in clicks if c.country), 8)
    top_devices = top(parsed[c.id][0] for c in clicks)
    top_browsers = top(parsed[c.id][1] for c in clicks)
    top_os = top(parsed[c.id][2] for c in clicks)
    top_referrers = top((c.referrer or "Direct") for c in clicks)

    # Recent 20 clicks
    recent = clicks[-20:][::-1]
    recent_clicks = [
        ClickRecord(
            timestamp=c.timestamp,
            ip_address=c.ip_address,
            user_agent=c.user_agent,
            country=c.country,
            device=parsed[c.id][0],
            browser=parsed[c.id][1],
            os=parsed[c.id][2],
            referrer=c.referrer,
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
        top_countries=top_countries,
        top_devices=top_devices,
        top_browsers=top_browsers,
        top_os=top_os,
        top_referrers=top_referrers,
        title=db_url.title,
        description=db_url.description,
        image_url=db_url.image_url,
    )


def _hide_protected(db_url: URL, user: Optional[User]) -> None:
    """A protected link's destination and stats are visible to its owner only."""
    if db_url.is_protected and (user is None or db_url.owner_id != user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This link is password-protected. Only its owner can see its details.",
        )


def _record_click(db: Session, short_code: str, request: Request, referrer: Optional[str]) -> None:
    user_agent = request.headers.get("User-Agent", "unknown")
    device, browser, os_name = parse_user_agent(user_agent)
    # Vercel's edge adds x-vercel-ip-country (ISO code). Elsewhere (local dev,
    # Docker) it is absent and country stays blank: no paid geo-IP lookups.
    country = (request.headers.get("x-vercel-ip-country") or "").strip().upper()[:8] or None
    db.add(Click(
        short_code=short_code,
        ip_address=client_ip(request),
        user_agent=user_agent,
        country=country,
        device=device,
        browser=browser,
        os=os_name,
        referrer=referrer,
    ))
    db.commit()


RESERVED = {"docs", "redoc", "openapi.json", "health", "shorten", "preview", "analytics",
            "favicon.ico", "auth", "me", "links"}


def _active_link(db: Session, short_code: str) -> URL:
    if short_code in RESERVED:
        raise HTTPException(status_code=404, detail="Not found")
    db_url = db.query(URL).filter(URL.short_code == short_code, URL.is_active == True).first()
    if not db_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Short code '{short_code}' not found or has been deactivated."
        )
    if is_expired(db_url.expires_at):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This shortened URL has expired.")
    return db_url


# ──────────────────────────────────────────────
# GET /{short_code} — Redirect (DYNAMIC ROUTE AT END)
# ──────────────────────────────────────────────
@router.get("/{short_code}")
async def redirect_to_url(short_code: str, request: Request, db: Session = Depends(get_db)):
    """
    Redirect short code to the original URL.
    Checks Redis cache first (unprotected links only); falls back to the database.
    Password-protected links get a small password page instead.
    Records click analytics.
    """
    if short_code in RESERVED:
        raise HTTPException(status_code=404, detail="Not found")

    original_url = await get_cached_url(short_code)
    if not original_url:
        db_url = _active_link(db, short_code)
        if db_url.is_protected:
            return password_page(short_code, ref=referrer_host(request.headers.get("Referer")) or "")
        original_url = db_url.original_url
        await set_cached_url(short_code, original_url)

    _record_click(db, short_code, request, referrer_host(request.headers.get("Referer")))
    # 302 (temporary) so browsers re-check and every click is counted
    return RedirectResponse(url=original_url, status_code=302)


# ──────────────────────────────────────────────
# POST /{short_code} — Unlock a password-protected link
# ──────────────────────────────────────────────
MAX_FORM_BYTES = 4096


@router.post("/{short_code}")
async def unlock_url(short_code: str, request: Request, db: Session = Depends(get_db)):
    """Check the password from the password page; on success record the click and redirect."""
    db_url = _active_link(db, short_code)
    if not db_url.is_protected:
        return RedirectResponse(url=db_url.original_url, status_code=303)

    body = await request.body()
    if len(body) > MAX_FORM_BYTES:
        raise HTTPException(status_code=413, detail="Request too large.")
    form = parse_qs(body.decode("utf-8", errors="replace"), max_num_fields=5)
    password = (form.get("password") or [""])[0]
    ref = ((form.get("ref") or [""])[0])[:255]

    key = f"{short_code}:{client_ip(request)}"
    if is_rate_limited(db, "unlock", key) or is_rate_limited(db, "unlock-link", short_code):
        return password_page(short_code, ref=ref, error="Too many wrong attempts. Try again in 15 minutes.",
                             status_code=429)
    if not password or not verify_password(password, db_url.password_hash):
        record_event(db, "unlock", key)
        record_event(db, "unlock-link", short_code)
        return password_page(short_code, ref=ref, error="Wrong password. Try again.", status_code=401)

    _record_click(db, short_code, request, referrer_host(f"https://{ref}") if ref else None)
    return RedirectResponse(url=db_url.original_url, status_code=303)


def password_page(code: str, ref: str = "", error: str = "", status_code: int = 200) -> HTMLResponse:
    """Small self-contained page asking for the link password (no scripts, no external assets)."""
    e = html.escape
    error_html = f'<p class="err" role="alert">{e(error)}</p>' if error else ""
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Protected link · SnapLink</title>
<style>
:root{{color-scheme:light dark;--bg:#f6f7fb;--card:#fff;--text:#0f1222;--muted:#5f6680;--border:#c9cfdc;--primary:#4f46e5;--on:#fff;--danger:#c02634}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b0d14;--card:#141826;--text:#eef0f7;--muted:#9198b0;--border:#363e56;--primary:#7c78ff;--on:#0b0d14;--danger:#ff7b86}}}}
*{{box-sizing:border-box;margin:0}}
body{{min-height:100vh;display:grid;place-items:center;padding:16px;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
main{{width:100%;max-width:380px;background:var(--card);border:1px solid var(--border);border-radius:18px;padding:28px 24px;box-shadow:0 20px 40px -16px rgba(0,0,0,.25)}}
.brand{{font-weight:800;letter-spacing:-.02em;color:var(--primary);margin-bottom:16px}}
h1{{font-size:20px;letter-spacing:-.01em}}
p.sub{{color:var(--muted);font-size:14px;margin:6px 0 18px}}
code{{font:600 14px ui-monospace,SFMono-Regular,Menlo,monospace}}
label{{display:block;font-size:14px;font-weight:600;margin-bottom:6px}}
input{{width:100%;height:46px;padding:0 14px;border:1px solid var(--border);border-radius:12px;background:transparent;color:inherit;font:inherit}}
input:focus{{outline:none;border-color:var(--primary);box-shadow:0 0 0 3px color-mix(in srgb,var(--primary) 35%,transparent)}}
button{{margin-top:14px;width:100%;height:46px;border:0;border-radius:12px;background:var(--primary);color:var(--on);font:600 15px system-ui,sans-serif;cursor:pointer}}
.err{{color:var(--danger);font-size:14px;font-weight:500;margin-top:10px}}
</style></head>
<body><main>
<p class="brand">SnapLink</p>
<h1>This link is password-protected</h1>
<p class="sub">Enter the password to continue to <code>/{e(code)}</code>.</p>
<form method="post" autocomplete="off">
<label for="pw">Password</label>
<input id="pw" name="password" type="password" required autofocus maxlength="200">
<input type="hidden" name="ref" value="{e(ref)}">
{error_html}
<button type="submit">Continue</button>
</form>
</main></body></html>"""
    return HTMLResponse(page, status_code=status_code, headers={
        "Cache-Control": "no-store",
        # No form-action directive: browsers apply it to the post-submit redirect too,
        # which would block the hop to the (external) destination.
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
        "X-Frame-Options": "DENY",
        # same-origin (not no-referrer): the form POST must carry a real Origin for the
        # CSRF check, while the destination still receives no Referer
        "Referrer-Policy": "same-origin",
        "X-Content-Type-Options": "nosniff",
    })
