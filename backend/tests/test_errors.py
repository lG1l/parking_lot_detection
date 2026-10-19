import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.errors import ApiError, install_error_handlers
from app.main import app


def test_health():
    assert TestClient(app).get("/api/health").json() == {"status": "ok"}


def test_unknown_path_uses_error_shape():
    r = TestClient(app).get("/api/nope")
    assert r.status_code == 404
    assert set(r.json()["error"]) == {"code", "message"}


def test_validation_and_api_error_and_500():
    class Body(BaseModel):
        n: int

    sub = FastAPI()
    install_error_handlers(sub)

    @sub.post("/v")
    def v(b: Body):
        return {}

    @sub.get("/a")
    def a():
        raise ApiError(409, "INVALID_STATE", "x")

    @sub.get("/b")
    def b():
        raise RuntimeError("secret detail")

    c = TestClient(sub, raise_server_exceptions=False)
    r = c.post("/v", json={"n": "secret-value"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_FAILED"
    assert "secret-value" not in r.text
    assert c.get("/a").json() == {"error": {"code": "INVALID_STATE", "message": "x"}}
    r = c.get("/b")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret detail" not in r.text


def test_app_does_not_import_local():
    assert not [m for m in sys.modules if m == "local" or m.startswith("local.")]
