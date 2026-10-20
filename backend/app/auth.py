"""
auth.py - Accounts, sessions, CSRF protection, rate limiting and the "My links" API.

Sessions: a short JWT (HS256, signed with JWT_SECRET) in an httpOnly, Secure,
SameSite=Lax cookie. The frontend reaches the API through its own /api proxy,
so the cookie is first-party on the frontend's domain.

CSRF: SameSite=Lax already stops cross-site POST/PATCH/DELETE from carrying the
cookie in modern browsers; on top of that every state-changing request that
carries the session cookie must send an Origin (or Referer) from an allowed
origin (see `csrf_origin_check`, installed as middleware in main.py).

Endpoints:
  POST   /auth/signup        - create an account and log in
  POST   /auth/login         - log in (rate-limited)
  POST   /auth/logout        - clear the session cookie
  GET    /auth/me            - the logged-in user (401 if none)
  GET    /me/links           - the user's links with click counts (search with ?q=)
  PATCH  /links/{code}       - change or remove a link's expiry (owner only)
  DELETE /links/{code}       - delete a link and its clicks (owner only)
"""

import os
import re
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlsplit

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .models import URL, Click, User, RateEvent
from .cache import delete_cached_url
from .utils import is_expired

logger = logging.getLogger(__name__)
router = APIRouter()

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
SESSION_COOKIE = "snaplink_session"
SESSION_DAYS = 7
JWT_ALG = "HS256"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "1") != "0"   # set 0 only for plain-http local dev
BCRYPT_ROUNDS = int(os.getenv("BCRYPT_ROUNDS", "12"))

_JWT_SECRET = os.getenv("JWT_SECRET", "")
if not _JWT_SECRET:
    if os.getenv("VERCEL_ENV") in ("production", "preview"):
        logger.error("JWT_SECRET is not set: accounts are disabled until it is configured.")
    else:
        # Local dev only: sessions reset whenever the process restarts.
        _JWT_SECRET = secrets.token_urlsafe(48)
        logger.warning("JWT_SECRET not set; using a random per-process secret (local dev).")


def _jwt_secret() -> str:
    if not _JWT_SECRET:
        raise HTTPException(status_code=503, detail="Accounts are not configured on this server.")
    return _JWT_SECRET


def allowed_origins() -> set[str]:
    """Origins allowed to make cookie-authenticated, state-changing requests."""
    origins = {o.strip().rstrip("/") for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()}
    base = os.getenv("BASE_URL", "http://localhost:8000")
    parts = urlsplit(base)
    if parts.scheme and parts.netloc:
        origins.add(f"{parts.scheme}://{parts.netloc}")
    origins.update({"http://localhost:5500", "http://127.0.0.1:5500", "http://localhost:3000"}
                   if not COOKIE_SECURE else set())
    return origins


# ──────────────────────────────────────────────
# Passwords
# ──────────────────────────────────────────────
MIN_PASSWORD, MAX_PASSWORD_BYTES = 8, 72      # bcrypt only uses the first 72 bytes
MIN_LINK_PASSWORD = 4

_dummy_hash: Optional[bytes] = None


def _get_dummy_hash() -> bytes:
    """Hash of a random string, used so unknown emails take as long as wrong passwords."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = bcrypt.hashpw(secrets.token_bytes(16), bcrypt.gensalt(rounds=BCRYPT_ROUNDS))
    return _dummy_hash


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, hashed: Optional[str]) -> bool:
    try:
        if not hashed:
            bcrypt.checkpw(password.encode("utf-8"), _get_dummy_hash())
            return False
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        return False


def validate_password(value: str, minimum: int = MIN_PASSWORD) -> str:
    if len(value) < minimum:
        raise ValueError(f"Password must be at least {minimum} characters.")
    if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")
    return value


# ──────────────────────────────────────────────
# Rate limiting (database-backed: works across serverless instances)
# ──────────────────────────────────────────────
LIMITS = {
    # bucket: (max failures, window)
    "login-email": (5, timedelta(minutes=15)),
    "login-ip": (20, timedelta(minutes=15)),
    "signup-ip": (10, timedelta(hours=1)),
    "unlock": (5, timedelta(minutes=15)),          # per short code + IP
}


def client_ip(request: Request) -> str:
    """Vercel overwrites X-Forwarded-For with the real client IP, so the first hop is trusted."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:45]
    return (request.client.host if request.client else "unknown")[:45]


def is_rate_limited(db: Session, bucket: str, key: str) -> bool:
    limit, window = LIMITS[bucket]
    since = datetime.utcnow() - window
    count = db.query(func.count(RateEvent.id)).filter(
        RateEvent.bucket == bucket, RateEvent.key == key[:300], RateEvent.created_at >= since
    ).scalar()
    return count >= limit


def record_event(db: Session, bucket: str, key: str) -> None:
    db.add(RateEvent(bucket=bucket, key=key[:300]))
    # Opportunistic cleanup of old rows (cheap, keeps the table small)
    if secrets.randbelow(50) == 0:
        db.query(RateEvent).filter(RateEvent.created_at < datetime.utcnow() - timedelta(days=1)).delete()
    db.commit()


def too_many(retry_minutes: int = 15) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many attempts. Try again in {retry_minutes} minutes.",
        headers={"Retry-After": str(retry_minutes * 60)},
    )


# ──────────────────────────────────────────────
# Sessions
# ──────────────────────────────────────────────
def _issue_session(response: Response, user: User) -> None:
    now = datetime.utcnow()
    token = jwt.encode(
        {"sub": str(user.id), "iat": now, "exp": now + timedelta(days=SESSION_DAYS)},
        _jwt_secret(), algorithm=JWT_ALG,
    )
    response.set_cookie(
        SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True,
        secure=COOKIE_SECURE, samesite="lax", path="/",
    )


def _clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=COOKIE_SECURE, samesite="lax")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """The logged-in user, or None. Invalid/expired tokens count as logged out."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token or not _JWT_SECRET:
        return None
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[JWT_ALG], options={"require": ["exp", "sub"]})
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, ValueError):
        return None
    return db.get(User, user_id)


def require_user(user: Optional[User] = Depends(get_current_user)) -> User:
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please log in first.")
    return user


# ──────────────────────────────────────────────
# CSRF: Origin check for cookie-authenticated unsafe requests
# ──────────────────────────────────────────────
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


async def csrf_origin_check(request: Request, call_next):
    """
    Reject state-changing requests that carry the session cookie unless they come
    from an allowed origin. Requests without the cookie (anonymous API use, curl)
    are unaffected because there is no ambient authority to abuse.
    """
    if request.method in UNSAFE_METHODS and SESSION_COOKIE in request.cookies:
        origin = request.headers.get("origin")
        if not origin or origin == "null":
            ref = request.headers.get("referer")
            if ref:
                p = urlsplit(ref)
                origin = f"{p.scheme}://{p.netloc}"
        if not origin or origin.rstrip("/") not in allowed_origins():
            return JSONResponse(status_code=403, content={"detail": "Cross-site request blocked."})
    return await call_next(request)


# ──────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")


class Credentials(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def check_email(cls, v):
        v = v.strip().lower()
        if len(v) > 254 or not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address.")
        return v


class SignupRequest(Credentials):
    @field_validator("password")
    @classmethod
    def check_password(cls, v):
        return validate_password(v)


class UserOut(BaseModel):
    id: int
    email: str
    created_at: datetime


class MyLink(BaseModel):
    short_url: str
    short_code: str
    original_url: str
    title: Optional[str] = None
    created_at: datetime
    expires_at: Optional[datetime] = None
    expired: bool
    password_protected: bool
    total_clicks: int


class MyLinksResponse(BaseModel):
    total: int
    links: list[MyLink]


class LinkUpdate(BaseModel):
    """`expires_in_days`: positive number of days from now, or null to never expire."""
    expires_in_days: Optional[int]

    @field_validator("expires_in_days")
    @classmethod
    def check_days(cls, v):
        if v is not None and not (1 <= v <= 3650):
            raise ValueError("expires_in_days must be between 1 and 3650, or null for no expiry.")
        return v


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, created_at=user.created_at)


def _short_url(code: str) -> str:
    return f"{os.getenv('BASE_URL', 'http://localhost:8000')}/{code}"


# ──────────────────────────────────────────────
# Auth endpoints
# ──────────────────────────────────────────────
@router.post("/auth/signup", response_model=UserOut, status_code=201)
async def signup(payload: SignupRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    _jwt_secret()
    ip = client_ip(request)
    if is_rate_limited(db, "signup-ip", ip):
        raise too_many(60)
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists. Log in instead.")
    user = User(email=payload.email, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists. Log in instead.")
    db.refresh(user)
    record_event(db, "signup-ip", ip)   # counts sign-ups per IP, not only failures
    _issue_session(response, user)
    return _user_out(user)


@router.post("/auth/login", response_model=UserOut)
async def login(payload: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    _jwt_secret()
    ip = client_ip(request)
    if is_rate_limited(db, "login-email", payload.email) or is_rate_limited(db, "login-ip", ip):
        raise too_many()
    user = db.query(User).filter(User.email == payload.email).first()
    if not verify_password(payload.password, user.password_hash if user else None):
        record_event(db, "login-email", payload.email)
        record_event(db, "login-ip", ip)
        raise HTTPException(status_code=401, detail="Wrong email or password.")
    _issue_session(response, user)
    return _user_out(user)


@router.post("/auth/logout", status_code=204)
async def logout():
    response = Response(status_code=204)
    _clear_session(response)
    return response


@router.get("/auth/me", response_model=UserOut)
async def me(user: User = Depends(require_user)):
    return _user_out(user)


# ──────────────────────────────────────────────
# Dashboard: the user's links
# ──────────────────────────────────────────────
@router.get("/me/links", response_model=MyLinksResponse)
async def my_links(q: str = "", limit: int = 200, user: User = Depends(require_user), db: Session = Depends(get_db)):
    limit = max(1, min(limit, 500))
    clicks = (
        db.query(Click.short_code, func.count(Click.id).label("n"))
        .group_by(Click.short_code).subquery()
    )
    query = (
        db.query(URL, func.coalesce(clicks.c.n, 0))
        .outerjoin(clicks, clicks.c.short_code == URL.short_code)
        .filter(URL.owner_id == user.id)
    )
    q = q.strip()
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            func.lower(URL.original_url).like(like)
            | func.lower(URL.short_code).like(like)
            | func.lower(func.coalesce(URL.title, "")).like(like)
        )
    total = query.count()
    rows = query.order_by(URL.created_at.desc(), URL.id.desc()).limit(limit).all()
    return MyLinksResponse(total=total, links=[
        MyLink(
            short_url=_short_url(u.short_code), short_code=u.short_code, original_url=u.original_url,
            title=u.title, created_at=u.created_at, expires_at=u.expires_at,
            expired=is_expired(u.expires_at), password_protected=u.is_protected, total_clicks=n,
        )
        for u, n in rows
    ])


def _owned_link(code: str, user: User, db: Session) -> URL:
    link = db.query(URL).filter(URL.short_code == code).first()
    if not link:
        raise HTTPException(status_code=404, detail=f"Short code '{code}' not found.")
    if link.owner_id != user.id:
        raise HTTPException(status_code=403, detail="You can only change links you own.")
    return link


@router.patch("/links/{code}", response_model=MyLink)
async def update_link(code: str, payload: LinkUpdate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    link = _owned_link(code, user, db)
    link.expires_at = (
        datetime.utcnow() + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None
    )
    db.commit()
    db.refresh(link)
    await delete_cached_url(code)
    n = db.query(func.count(Click.id)).filter(Click.short_code == code).scalar()
    return MyLink(
        short_url=_short_url(code), short_code=code, original_url=link.original_url, title=link.title,
        created_at=link.created_at, expires_at=link.expires_at, expired=is_expired(link.expires_at),
        password_protected=link.is_protected, total_clicks=n,
    )


@router.delete("/links/{code}", status_code=204)
async def delete_link(code: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    link = _owned_link(code, user, db)
    db.query(Click).filter(Click.short_code == code).delete()
    db.delete(link)
    db.commit()
    await delete_cached_url(code)
    return Response(status_code=204)
