from sqlalchemy import text

from app.db import get_engine
from app.security import hash_password, token_hash


def make_user(login_id="demo", password="demo-password", name="시연용"):
    with get_engine().begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO users (login_id, password_hash, name) VALUES (:l, :p, :n) RETURNING id"
            ),
            {"l": login_id, "p": hash_password(password), "n": name},
        ).scalar_one()


def count(sql):
    with get_engine().connect() as conn:
        return conn.execute(text(sql)).scalar_one()


def test_login_me_logout(client):
    uid = make_user()
    r = client.post("/api/auth/login", json={"login_id": "demo", "password": "demo-password"})
    assert r.status_code == 200
    assert r.json() == {"id": uid, "login_id": "demo", "name": "시연용"}
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "max-age=604800" in cookie
    assert "secure" not in cookie

    assert client.get("/api/auth/me").json()["login_id"] == "demo"

    r = client.post("/api/auth/logout")
    assert r.status_code == 204
    assert "max-age=0" in r.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").status_code == 401
    assert count("SELECT count(*) FROM sessions") == 0


def test_session_stores_only_hash(client):
    make_user()
    client.post("/api/auth/login", json={"login_id": "demo", "password": "demo-password"})
    sid = client.cookies["sid"]
    with get_engine().connect() as conn:
        stored = conn.execute(text("SELECT token_hash FROM sessions")).scalar_one()
    assert stored == token_hash(sid) and stored != sid


def test_login_failure_does_not_reveal_which_is_wrong(client):
    make_user()
    wrong_pw = client.post("/api/auth/login", json={"login_id": "demo", "password": "nope"})
    no_user = client.post("/api/auth/login", json={"login_id": "ghost", "password": "nope"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()
    assert wrong_pw.json()["error"]["code"] == "LOGIN_FAILED"
    assert "set-cookie" not in wrong_pw.headers
    assert count("SELECT count(*) FROM sessions") == 0


def test_login_rejects_empty_and_overlong(client):
    make_user()
    r = client.post("/api/auth/login", json={"login_id": "demo", "password": ""})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_FAILED"
    r = client.post("/api/auth/login", json={"login_id": "demo", "password": "a" * 100})
    assert r.status_code == 401


def test_me_requires_login(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_expired_session_is_rejected(client):
    make_user()
    client.post("/api/auth/login", json={"login_id": "demo", "password": "demo-password"})
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE sessions SET expires_at = now() - interval '1 second'"))
    assert client.get("/api/auth/me").status_code == 401


def test_logout_without_cookie_is_204(client):
    assert client.post("/api/auth/logout").status_code == 204


def test_logout_ends_only_this_browser(client):
    from fastapi.testclient import TestClient

    from app.main import app

    make_user()
    body = {"login_id": "demo", "password": "demo-password"}
    other = TestClient(app)
    client.post("/api/auth/login", json=body)
    other.post("/api/auth/login", json=body)
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    assert other.get("/api/auth/me").status_code == 200


def test_login_writes_access_log_even_if_ip_is_not_valid(client):
    uid = make_user()
    client.post("/api/auth/login", json={"login_id": "demo", "password": "demo-password"})
    with get_engine().connect() as conn:
        row = conn.execute(text("SELECT user_id, action FROM access_logs")).one()
    assert (row.user_id, row.action) == (uid, "login")


def test_failed_login_leaves_no_access_log(client):
    make_user()
    client.post("/api/auth/login", json={"login_id": "demo", "password": "nope"})
    assert count("SELECT count(*) FROM access_logs") == 0
