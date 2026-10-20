from .conftest import ORIGIN, new_client


def make_protected(c, password="open sesame", url="https://example.com/secret"):
    r = c.post("/shorten", json={"url": url, "password": password}, headers=ORIGIN)
    assert r.status_code == 201, r.text
    assert r.json()["password_protected"] is True
    assert "open sesame" not in r.text and "password_hash" not in r.text
    return r.json()["short_code"]


def clicks(c, code):
    return c.get(f"/analytics/{code}").json()["total_clicks"]


def test_password_page_then_unlock_records_click(user_client):
    code = make_protected(user_client)
    with new_client() as visitor:
        page = visitor.get(f"/{code}", headers={"Referer": "https://twitter.com/x"})
        assert page.status_code == 200 and "location" not in page.headers
        assert 'name="password"' in page.text and "example.com/secret" not in page.text
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert page.headers["cache-control"] == "no-store"
        # no-referrer would make browsers send "Origin: null" on the form POST
        assert page.headers["referrer-policy"] == "same-origin"

        bad = visitor.post(f"/{code}", data={"password": "nope", "ref": "twitter.com"}, headers=ORIGIN)
        assert bad.status_code == 401 and "Wrong password" in bad.text and "location" not in bad.headers
        assert clicks(user_client, code) == 0

        ok = visitor.post(f"/{code}", data={"password": "open sesame", "ref": "twitter.com"}, headers=ORIGIN)
        assert ok.status_code == 303 and ok.headers["location"] == "https://example.com/secret"
    stats = user_client.get(f"/analytics/{code}").json()
    assert stats["total_clicks"] == 1 and stats["top_referrers"][0]["name"] == "twitter.com"


def test_wrong_passwords_are_rate_limited(user_client):
    code = make_protected(user_client)
    with new_client() as attacker:
        for _ in range(5):
            assert attacker.post(f"/{code}", data={"password": "guess"}).status_code == 401
        locked = attacker.post(f"/{code}", data={"password": "open sesame"})
        assert locked.status_code == 429 and "location" not in locked.headers
    with new_client() as someone_else:   # limit is per link + IP
        assert someone_else.post(f"/{code}", data={"password": "open sesame"}).status_code == 303


def test_protected_details_are_owner_only(user_client):
    code = make_protected(user_client)
    with new_client() as anon:
        assert anon.get(f"/analytics/{code}").status_code == 403
        assert anon.get(f"/preview/{code}").status_code == 403
    assert user_client.get(f"/analytics/{code}").status_code == 200
    assert user_client.get(f"/preview/{code}").json()["original_url"] == "https://example.com/secret"


def test_anonymous_protected_link_and_no_dedupe(client):
    r1 = client.post("/shorten", json={"url": "https://example.com/p", "password": "pass1234"})
    r2 = client.post("/shorten", json={"url": "https://example.com/p"})
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["short_code"] != r2.json()["short_code"]       # protected link never reused
    assert client.get(f"/{r2.json()['short_code']}").status_code == 302


def test_link_password_validation(client):
    assert client.post("/shorten", json={"url": "https://example.com/v", "password": "abc"}).status_code == 422
    assert client.post("/shorten", json={"url": "https://example.com/v", "password": "x" * 73}).status_code == 422
