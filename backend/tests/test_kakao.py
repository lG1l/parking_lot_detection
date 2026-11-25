from urllib.parse import parse_qs, urlsplit

import pytest

from app import kakao, rate_limit
from app.config import get_settings
from tests.conftest import make_client
from tests.test_auth import count, make_user
from tests.test_videos import sql

GOOD = {"login_id": "parkadmin1", "password": "Parking2026!", "name": "김관리", "role": "admin"}


@pytest.fixture
def configured(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "kakao_rest_api_key", "rest-key")
    monkeypatch.setattr(s, "kakao_client_secret", "secret")
    monkeypatch.setattr(s, "kakao_redirect_uri", "http://localhost:8000/api/auth/kakao/callback")


@pytest.fixture
def kakao_id(monkeypatch, configured):
    """카카오 호출 대신 정해 둔 회원번호를 준다. 값을 None으로 바꾸면 실패를 흉내 낸다."""
    box = {"id": 1001, "codes": []}

    def fake(code):
        box["codes"].append(code)
        return box["id"]

    monkeypatch.setattr(kakao, "kakao_user_id", fake)
    return box


def code(r):
    return r.status_code, r.json()["error"]["code"]


def start(client, **override):
    return client.post("/api/auth/signup/start", json={**GOOD, **override})


def state_of(r):
    return parse_qs(urlsplit(r.json()["authorize_url"]).query)["state"][0]


def callback(client, state, **params):
    return client.get(
        "/api/auth/kakao/callback",
        params={"state": state, "code": "c", **params},
        follow_redirects=False,
    )


def signup(client, **override):
    return callback(client, state_of(start(client, **override)))


# ---- 35번 가입 시작 ----


def test_start_returns_authorize_url_and_state_cookie(client, configured):
    r = start(client)
    assert r.status_code == 200
    url = urlsplit(r.json()["authorize_url"])
    q = parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == kakao.AUTHORIZE_URL
    assert q["client_id"] == ["rest-key"] and q["response_type"] == ["code"]
    assert q["redirect_uri"] == ["http://localhost:8000/api/auth/kakao/callback"]
    assert "secret" not in r.text
    cookie = r.headers["set-cookie"].lower()
    assert f"oauth_state={q['state'][0].lower()}" in cookie
    assert "httponly" in cookie and "path=/api/auth/kakao" in cookie and "max-age=600" in cookie
    row = sql("SELECT purpose, login_id, password_hash, state_hash FROM kakao_pending").one()
    assert row.purpose == "signup" and row.login_id == "parkadmin1"
    assert row.password_hash.startswith("$2") and q["state"][0] not in row.state_hash


@pytest.mark.parametrize(
    "override",
    [
        {"login_id": "abc"},  # 4자 미만
        {"login_id": "Parkadmin"},  # 대문자
        {"login_id": "a" * 21},
        {"password": "abcdefgh1"},  # 2종류 9자
        {"password": "Abcdef1"},  # 3종류 7자
        {"password": "abcdefghij"},  # 1종류
        {"password": "Parking2026!" + "가"},  # ASCII 아님
        {"password": "Aa1!" * 17},  # 65자
        {"login_id": "parkadmin10", "password": "parkadmin10"},  # 아이디와 같음
        {"name": ""},
        {"name": "   "},
        {"name": "가" * 21},
        {"name": "a\nb"},
        {"role": "owner"},
    ],
)
def test_start_rejects_bad_input(client, configured, override):
    assert code(start(client, **override)) == (422, "VALIDATION_FAILED")
    assert count("SELECT count(*) FROM kakao_pending") == 0


@pytest.mark.parametrize("password", ["abcdefgh12", "Abcdef1!", "Abcdefg1", "a b c d e 1"])
def test_start_accepts_password_rules(client, configured, password):
    assert start(client, password=password).status_code == 200


def test_start_rejects_taken_login_id(client, configured):
    make_user("parkadmin1")
    assert code(start(client)) == (409, "LOGIN_ID_TAKEN")


def test_start_without_kakao_keys_is_503(client):
    assert code(start(client)) == (503, "KAKAO_NOT_CONFIGURED")


def test_start_limited_per_ip(client, configured):
    for _ in range(kakao.START_LIMIT):
        assert start(client).status_code == 200
    r = start(client)
    assert code(r) == (429, "TOO_MANY_ATTEMPTS")
    assert 0 < int(r.headers["retry-after"]) <= 3600
    from fastapi.testclient import TestClient

    from app.main import app

    assert start(TestClient(app, client=("127.0.0.2", 50000))).status_code == 200


# ---- 36번 콜백 ----


def test_signup_creates_user_and_logs_in(client, kakao_id):
    r = signup(client)
    assert r.status_code == 302 and r.headers["location"] == "/"
    cookies = r.headers.get_list("set-cookie")
    assert any(c.startswith("sid=") and "HttpOnly" in c for c in cookies)
    assert any(c.startswith("oauth_state=") and "Max-Age=0" in c for c in cookies)
    me = client.get("/api/auth/me").json()
    assert me["login_id"] == "parkadmin1" and me["name"] == "김관리" and me["role"] == "admin"
    assert sql("SELECT kakao_id FROM users").scalar_one() == 1001
    assert count("SELECT count(*) FROM kakao_pending") == 0
    assert count("SELECT count(*) FROM access_logs WHERE action = 'login'") == 1
    # 입력한 비밀번호로 다시 로그인할 수 있다
    r = make_client().post(
        "/api/auth/login", json={"login_id": "parkadmin1", "password": "Parking2026!"}
    )
    assert r.status_code == 200


def test_state_is_single_use(client, kakao_id):
    state = state_of(start(client))
    assert callback(client, state).headers["location"] == "/"
    r = callback(client, state)
    assert r.headers["location"] == "/#/login?error=KAKAO_EXPIRED"
    assert count("SELECT count(*) FROM users") == 1


def test_state_must_match_cookie(client, kakao_id):
    """남의 브라우저에 내 인증을 끼워 넣지 못한다 (로그인 CSRF)."""
    attacker = make_client()
    state = state_of(start(attacker))
    r = callback(client, state)  # 피해자 브라우저에는 oauth_state 쿠키가 없다
    assert r.headers["location"] == "/#/login?error=KAKAO_EXPIRED"
    assert kakao_id["codes"] == [] and count("SELECT count(*) FROM users") == 0


def test_expired_pending(client, kakao_id):
    state = state_of(start(client))
    sql("UPDATE kakao_pending SET expires_at = now() - interval '1 second'")
    assert callback(client, state).headers["location"] == "/#/signup?error=KAKAO_EXPIRED"
    assert kakao_id["codes"] == []


def test_cancelled_on_kakao(client, kakao_id):
    state = state_of(start(client))
    r = callback(client, state, code="", error="access_denied")
    assert r.headers["location"] == "/#/signup?error=KAKAO_CANCELLED"
    assert count("SELECT count(*) FROM kakao_pending") == 0


def test_kakao_failure(client, kakao_id):
    kakao_id["id"] = None
    assert signup(client).headers["location"] == "/#/signup?error=KAKAO_FAILED"
    assert count("SELECT count(*) FROM users") == 0


def test_one_account_per_kakao(client, kakao_id):
    signup(client)
    r = signup(make_client(), login_id="another1")
    assert r.headers["location"] == "/#/signup?error=KAKAO_ALREADY_USED"
    assert count("SELECT count(*) FROM users") == 1


def test_login_id_taken_meanwhile(client, kakao_id):
    state = state_of(start(client))
    make_user("parkadmin1")
    assert callback(client, state).headers["location"] == "/#/signup?error=LOGIN_ID_TAKEN"


def test_expired_pending_cleanup(client, configured):
    from app.periodic import delete_expired_kakao_pending

    start(client)
    start(client, login_id="other1")
    sql(
        "UPDATE kakao_pending SET expires_at = now() - interval '1 second' WHERE login_id = 'other1'"
    )
    delete_expired_kakao_pending()
    assert sql("SELECT login_id FROM kakao_pending").scalars().all() == ["parkadmin1"]


# ---- 1번 로그인 실패 제한 ----


def fail_login(client, login_id="demo"):
    return client.post("/api/auth/login", json={"login_id": login_id, "password": "wrong"})


def test_login_blocked_after_5_failures_per_id(client):
    make_user()
    for _ in range(5):
        assert code(fail_login(client)) == (401, "LOGIN_FAILED")
    r = client.post("/api/auth/login", json={"login_id": "demo", "password": "demo-password"})
    assert code(r) == (429, "TOO_MANY_ATTEMPTS")
    assert 890 <= int(r.headers["retry-after"]) <= 900
    # 다른 아이디는 같은 IP여도 아직 된다
    make_user("other")
    r = client.post("/api/auth/login", json={"login_id": "other", "password": "demo-password"})
    assert r.status_code == 200


def test_login_blocked_after_30_failures_per_ip(client):
    make_user()
    for i in range(30):
        assert fail_login(client, f"nobody{i}").status_code == 401
    r = client.post("/api/auth/login", json={"login_id": "demo", "password": "demo-password"})
    assert code(r) == (429, "TOO_MANY_ATTEMPTS")


def test_login_success_clears_failures(client):
    make_user()
    for _ in range(4):
        fail_login(client)
    assert (
        client.post(
            "/api/auth/login", json={"login_id": "demo", "password": "demo-password"}
        ).status_code
        == 200
    )
    for _ in range(4):
        assert fail_login(client).status_code == 401


def test_login_block_expires(client, monkeypatch):
    make_user()
    now = [1000.0]
    monkeypatch.setattr(rate_limit, "_now", lambda: now[0])
    for _ in range(5):
        fail_login(client)
    assert fail_login(client).status_code == 429
    now[0] += 15 * 60
    assert fail_login(client).status_code == 401


# ---- 카카오 호출 ----


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def fake_requests(monkeypatch, token, me):
    seen = {}

    def post(url, data, timeout):
        seen["post"] = (url, data, timeout)
        return token

    def get(url, headers, timeout):
        seen["get"] = (url, headers)
        return me

    monkeypatch.setattr(kakao.requests, "post", post)
    monkeypatch.setattr(kakao.requests, "get", get)
    return seen


def test_kakao_user_id_exchanges_code_on_server(monkeypatch, configured):
    seen = fake_requests(
        monkeypatch, FakeResp(200, {"access_token": "tok"}), FakeResp(200, {"id": 42})
    )
    assert kakao.kakao_user_id("the-code") == 42
    url, data, timeout = seen["post"]
    assert url == kakao.TOKEN_URL and timeout == kakao.KAKAO_TIMEOUT
    assert data["code"] == "the-code" and data["client_secret"] == "secret"
    assert data["grant_type"] == "authorization_code"
    assert seen["get"] == (kakao.USER_URL, {"Authorization": "Bearer tok"})


@pytest.mark.parametrize(
    "token, me",
    [
        (FakeResp(401, {"error": "invalid_grant", "code": "code-zz9"}), None),
        (FakeResp(200, {"access_token": "tok-zz9"}), FakeResp(401, {})),
        (FakeResp(200, {"access_token": "tok-zz9"}), FakeResp(200, {"id": "42"})),
        (FakeResp(200, {}), None),
    ],
)
def test_kakao_user_id_failures(monkeypatch, configured, caplog, token, me):
    fake_requests(monkeypatch, token, me)
    assert kakao.kakao_user_id("code-zz9") is None
    assert "code-zz9" not in caplog.text and "tok-zz9" not in caplog.text
