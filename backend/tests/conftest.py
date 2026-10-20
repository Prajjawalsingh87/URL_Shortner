"""Test setup: temp SQLite DB, fixed secrets, no network (reachability/preview stubbed)."""
import itertools
import os
import tempfile

import pytest

_db_dir = tempfile.mkdtemp(prefix="snaplink-tests-")
os.environ.update({
    "VERCEL": "1",                                   # NullPool engine (works with SQLite)
    "DATABASE_URL": f"sqlite:///{_db_dir}/test.db",
    "JWT_SECRET": "test-secret-not-used-anywhere-else-0123456789",
    "COOKIE_SECURE": "0",                            # TestClient talks plain http
    "BCRYPT_ROUNDS": "4",                            # fast hashing in tests
    "BASE_URL": "http://testserver",
    "ALLOWED_ORIGINS": "http://testserver",
    "REDIS_URL": "redis://127.0.0.1:1/0",            # unreachable: cache disabled
})

from fastapi.testclient import TestClient  # noqa: E402

from app import routes  # noqa: E402
from app.main import app  # noqa: E402

ORIGIN = {"Origin": "http://testserver"}
_ips = itertools.count(1)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    async def reachable(url, timeout=5.0):
        return (False, "Connection failed") if "unreachable" in url else (True, "OK")

    async def preview(url):
        return {"title": "Example title"}

    monkeypatch.setattr(routes, "is_url_reachable", reachable)
    monkeypatch.setattr(routes, "fetch_link_preview", preview)


def new_client() -> TestClient:
    """A browser-like client with its own cookie jar and its own client IP (rate limits are per IP)."""
    c = TestClient(app, follow_redirects=False)
    c.headers["X-Forwarded-For"] = f"203.0.113.{next(_ips) % 250 + 1}"
    return c


_emails = itertools.count(1)


def signup(client: TestClient, password: str = "correct horse battery") -> str:
    email = f"user{next(_emails)}@example.com"
    r = client.post("/auth/signup", json={"email": email, "password": password}, headers=ORIGIN)
    assert r.status_code == 201, r.text
    return email


@pytest.fixture
def client():
    with new_client() as c:
        yield c


@pytest.fixture
def user_client():
    with new_client() as c:
        c.email = signup(c)
        yield c
