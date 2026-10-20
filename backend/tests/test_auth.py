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


def test_login_is_rate_limited_per_email(client):
    email = signup(client, password="s3cret-password")
    client.cookies.clear()
    for _ in range(5):
        assert client.post("/auth/login", json={"email": email, "password": "bad-password"}).status_code == 401
    # Locked even with the right password, and from another IP
    with new_client() as other:
        r = other.post("/auth/login", json={"email": email, "password": "s3cret-password"})
        assert r.status_code == 429 and "Retry-After" in r.headers


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
