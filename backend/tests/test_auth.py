from app.auth import SESSION_COOKIE
from .conftest import ORIGIN, new_client, signup


def test_signup_sets_httponly_session_and_me(client):
    email = signup(client)
    cookie = next(c for c in client.cookies.jar if c.name == SESSION_COOKIE)
    assert cookie.has_nonstandard_attr("HttpOnly")
    r = client.get("/auth/me")
    assert r.status_code == 200 and r.json()["email"] == email
    assert "password" not in r.text


def test_signup_validation_and_duplicates(client):
    assert client.post("/auth/signup", json={"email": "nope", "password": "longenough"}).status_code == 422
    assert client.post("/auth/signup", json={"email": "a@example.com", "password": "short"}).status_code == 422
    assert client.post("/auth/signup", json={"email": "a@example.com", "password": "x" * 73}).status_code == 422
    email = signup(client)
    with new_client() as other:
        r = other.post("/auth/signup", json={"email": email.upper(), "password": "another password"})
        assert r.status_code == 409


def test_login_logout(client):
    email = signup(client, password="s3cret-password")
    client.post("/auth/logout", headers=ORIGIN)
    assert client.get("/auth/me").status_code == 401
    assert client.post("/auth/login", json={"email": email, "password": "wrong-password"}).status_code == 401
    r = client.post("/auth/login", json={"email": email.upper(), "password": "s3cret-password"})
    assert r.status_code == 200
    assert client.get("/auth/me").json()["email"] == email


def test_login_lockout_is_per_email_and_ip(client):
    email = signup(client, password="s3cret-password")
    client.cookies.clear()
    for _ in range(5):
        assert client.post("/auth/login", json={"email": email, "password": "bad-password"}).status_code == 401
    # This IP is locked out for this account, even with the right password...
    r = client.post("/auth/login", json={"email": email, "password": "s3cret-password"})
    assert r.status_code == 429 and "Retry-After" in r.headers
    # ...but a stranger failing on purpose can't lock the real user out from elsewhere
    with new_client() as owner:
        assert owner.post("/auth/login", json={"email": email, "password": "s3cret-password"}).status_code == 200


def test_login_per_account_ceiling_across_ips(client):
    email = signup(client, password="s3cret-password")
    for _ in range(10):                      # 10 IPs x 5 failures = the 50 per-account ceiling
        with new_client() as attacker:
            for _ in range(5):
                attacker.post("/auth/login", json={"email": email, "password": "guess-guess"})
    with new_client() as fresh_ip:
        assert fresh_ip.post("/auth/login", json={"email": email, "password": "s3cret-password"}).status_code == 429


def test_forwarded_for_only_trusted_behind_proxy(monkeypatch):
    from starlette.requests import Request
    from app import auth
    req = Request({"type": "http", "headers": [(b"x-forwarded-for", b"1.2.3.4")], "client": ("10.9.8.7", 1234)})
    monkeypatch.setattr(auth, "TRUST_PROXY", True)
    assert auth.client_ip(req) == "1.2.3.4"
    monkeypatch.setattr(auth, "TRUST_PROXY", False)
    assert auth.client_ip(req) == "10.9.8.7"


def test_csrf_and_cors_share_origins():
    from app import auth
    assert set(auth.configured_origins()) <= auth.allowed_origins()
    assert "http://testserver" in auth.allowed_origins()


def test_unknown_email_gets_same_error(client):
    r = client.post("/auth/login", json={"email": "ghost@example.com", "password": "whatever-pw"})
    assert r.status_code == 401 and r.json()["detail"] == "Wrong email or password."


def test_tampered_session_is_logged_out(client):
    signup(client)
    token = client.cookies.get(SESSION_COOKIE)
    client.cookies.set(SESSION_COOKIE, token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1])
    assert client.get("/auth/me").status_code == 401


def test_csrf_origin_check_for_cookie_requests(user_client):
    body = {"url": "https://example.com/csrf"}
    assert user_client.post("/shorten", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert user_client.post("/shorten", json=body).status_code == 403          # no Origin/Referer
    assert user_client.post("/shorten", json=body, headers={"Referer": "http://testserver/page"}).status_code == 201
    assert user_client.post("/shorten", json=body, headers=ORIGIN).status_code == 201


def test_anonymous_api_use_needs_no_origin(client):
    r = client.post("/shorten", json={"url": "https://example.com/anon"})
    assert r.status_code == 201 and r.json()["owned"] is False
