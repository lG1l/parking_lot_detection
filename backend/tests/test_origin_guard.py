import pytest
from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import access_log, auth
from app.config import Settings
from app.origin_guard import OriginGuard
from tests.test_auth import make_user

SECRET = "s" * 40


def guarded_client():
    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        await socket.accept()
        await socket.send_text("hi")
        await socket.close()

    app.add_middleware(OriginGuard, secret=SECRET)
    return TestClient(app)


def test_guard_passes_matching_header():
    r = guarded_client().get("/ping", headers={"X-Origin-Verify": SECRET})
    assert r.status_code == 200


@pytest.mark.parametrize("headers", [{}, {"X-Origin-Verify": "wrong"}])
def test_guard_blocks_missing_or_wrong_header(headers):
    r = guarded_client().get("/ping", headers=headers)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


def test_guard_websocket():
    c = guarded_client()
    with c.websocket_connect("/ws", headers={"X-Origin-Verify": SECRET}) as ws:
        assert ws.receive_text() == "hi"
    with pytest.raises(WebSocketDisconnect), c.websocket_connect("/ws"):
        pass


@pytest.fixture
def aws_mode(monkeypatch):
    settings = Settings.model_construct(app_mode="aws")
    monkeypatch.setattr(access_log, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)


def request_with(headers: dict, client=("10.0.0.5", 443)):
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": client})


@pytest.mark.parametrize(
    "value, ip",
    [
        ("198.51.100.10:46532", "198.51.100.10"),
        ("2001:db8::1:46532", "2001:db8::1"),
        ("not-an-ip:1", None),
    ],
)
def test_aws_ip_from_viewer_address(aws_mode, value, ip):
    assert access_log.client_ip(request_with({"CloudFront-Viewer-Address": value})) == ip


def test_aws_ignores_peer_and_forwarded_for(aws_mode):
    # 헤더가 없으면 접속한 쪽(CloudFront)이나 X-Forwarded-For로 대신하지 않는다
    assert access_log.client_ip(request_with({"X-Forwarded-For": "1.2.3.4"})) is None


def test_local_ip_from_peer():
    r = request_with({"CloudFront-Viewer-Address": "198.51.100.10:1"})
    assert access_log.client_ip(r) == "10.0.0.5"


def test_cookie_secure_only_in_aws(aws_mode):
    assert auth.cookie_secure() is True


def test_login_cookie_not_secure_in_local(client):
    make_user()
    r = client.post("/api/auth/login", json={"login_id": "demo", "password": "demo-password"})
    assert r.status_code == 200
    assert "secure" not in r.headers["set-cookie"].lower()
