from .conftest import ORIGIN, new_client, signup


def shorten(c, **body):
    body.setdefault("url", "https://example.com/")
    return c.post("/shorten", json=body, headers=ORIGIN)


def test_owned_links_dashboard_and_isolation(user_client):
    r = shorten(user_client, url="https://example.com/mine")
    assert r.status_code == 201 and r.json()["owned"] is True
    code = r.json()["short_code"]
    user_client.get(f"/{code}")
    user_client.get(f"/{code}")

    links = user_client.get("/me/links").json()
    assert links["total"] == 1
    assert links["links"][0]["short_code"] == code and links["links"][0]["total_clicks"] == 2
    assert user_client.get("/me/links?q=MINE").json()["total"] == 1
    assert user_client.get("/me/links?q=nothing-matches").json()["total"] == 0

    with new_client() as other:
        signup(other)
        assert other.get("/me/links").json()["total"] == 0
    with new_client() as anon:
        assert anon.get("/me/links").status_code == 401


def test_logged_in_user_does_not_reuse_anonymous_link(user_client):
    with new_client() as anon:
        anon_code = anon.post("/shorten", json={"url": "https://example.com/shared"}).json()["short_code"]
    mine = shorten(user_client, url="https://example.com/shared").json()
    assert mine["short_code"] != anon_code and mine["owned"] is True
    # ...but the same user shortening it again gets their own link back
    assert shorten(user_client, url="https://example.com/shared").json()["short_code"] == mine["short_code"]


def test_bulk_links_are_owned(user_client):
    r = user_client.post("/shorten/bulk", json={"urls": ["https://example.com/b1", "https://example.com/b2"]}, headers=ORIGIN)
    assert r.json()["succeeded"] == 2
    assert user_client.get("/me/links").json()["total"] == 2


def test_edit_expiry_ownership(user_client):
    code = shorten(user_client, url="https://example.com/exp").json()["short_code"]
    r = user_client.patch(f"/links/{code}", json={"expires_in_days": 7}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["expires_at"] is not None
    r = user_client.patch(f"/links/{code}", json={"expires_in_days": None}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["expires_at"] is None
    assert user_client.patch(f"/links/{code}", json={"expires_in_days": 0}, headers=ORIGIN).status_code == 422
    assert user_client.patch("/links/doesnotexist", json={"expires_in_days": 1}, headers=ORIGIN).status_code == 404

    with new_client() as other:
        signup(other)
        assert other.patch(f"/links/{code}", json={"expires_in_days": 1}, headers=ORIGIN).status_code == 403
    with new_client() as anon:
        assert anon.patch(f"/links/{code}", json={"expires_in_days": 1}).status_code == 401
        anon_code = anon.post("/shorten", json={"url": "https://example.com/anon-exp"}).json()["short_code"]
    # Anonymous links have no owner, so nobody can edit them
    assert user_client.patch(f"/links/{anon_code}", json={"expires_in_days": 1}, headers=ORIGIN).status_code == 403


def test_delete_ownership(user_client):
    code = shorten(user_client, url="https://example.com/del").json()["short_code"]
    user_client.get(f"/{code}")
    with new_client() as other:
        signup(other)
        assert other.delete(f"/links/{code}", headers=ORIGIN).status_code == 403
    assert user_client.delete(f"/links/{code}", headers=ORIGIN).status_code == 204
    assert user_client.get(f"/{code}").status_code == 404
    assert user_client.get(f"/analytics/{code}").status_code == 404


def test_expired_link_is_gone(user_client):
    from datetime import datetime, timedelta
    from app.database import SessionLocal
    from app.models import URL
    code = shorten(user_client, url="https://example.com/old").json()["short_code"]
    with SessionLocal() as db:
        db.query(URL).filter(URL.short_code == code).update({URL.expires_at: datetime.utcnow() - timedelta(days=1)})
        db.commit()
    assert user_client.get(f"/{code}").status_code == 410
