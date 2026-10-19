import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from app import storage
from app.db import get_engine
from app.security import token_hash
from tests.conftest import STORAGE, make_client
from tests.test_auth import count, make_user

AGREEMENT = {
    "version": "2026-10-12",
    "confirm_signage": True,
    "confirm_disclosure_judged": True,
    "confirm_reconsignment": True,
}
BODY = {"filename": "CH03.MP4", "size_bytes": 1000, "agreement": AGREEMENT}


def login(client, login_id="demo"):
    make_user(login_id=login_id)
    r = client.post("/api/auth/login", json={"login_id": login_id, "password": "demo-password"})
    assert r.status_code == 200
    return client


@pytest.fixture
def admin(client):
    return login(client)


def new_link(client):
    r = client.post("/api/upload-links")
    assert r.status_code == 201
    return r.json()["token"]


def presign(client, token, **override):
    return client.post(f"/api/uploads/{token}/presign", json={**BODY, **override})


def expire(token):
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE upload_tokens SET expires_at = now() - interval '1 second' "
                "WHERE token_hash = :h"
            ),
            {"h": token_hash(token)},
        )


def queue_files():
    queue = STORAGE / "scratch" / "backend" / "queue"
    return sorted(queue.glob("*.json")) if queue.exists() else []


def test_issue_requires_login(client):
    r = client.post("/api/upload-links")
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_issue_stores_only_hash(admin):
    r = admin.post("/api/upload-links")
    body = r.json()
    assert len(body["token"]) == 43 and body["expires_at"].endswith("+09:00")
    with get_engine().connect() as conn:
        stored = conn.execute(text("SELECT token_hash FROM upload_tokens")).scalar_one()
    assert stored == token_hash(body["token"]) and body["token"] not in stored


def test_reissue_invalidates_previous_link(admin):
    old = new_link(admin)
    new = new_link(admin)
    r = admin.get(f"/api/uploads/{old}")
    assert r.status_code == 410 and r.json()["error"]["code"] == "UPLOAD_TOKEN_EXPIRED"
    assert admin.get(f"/api/uploads/{new}").status_code == 200


def test_reissue_keeps_used_link(admin):
    old = new_link(admin)
    assert presign(admin, old).status_code == 200
    new_link(admin)
    with get_engine().connect() as conn:
        expires_ok = conn.execute(
            text("SELECT expires_at > now() FROM upload_tokens WHERE token_hash = :h"),
            {"h": token_hash(old)},
        ).scalar_one()
    assert expires_ok  # 이미 쓴 링크는 건드리지 않는다


def test_concurrent_issue_leaves_one_live_link():
    clients = [login(make_client(), "demo")] + [make_client()]
    clients[1].post("/api/auth/login", json={"login_id": "demo", "password": "demo-password"})
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda c: c.post("/api/upload-links").status_code, clients))
    assert results == [201, 201]
    assert (
        count("SELECT count(*) FROM upload_tokens WHERE used_at IS NULL AND expires_at > now()")
        == 1
    )


def test_check_link_codes(admin):
    r = admin.get("/api/uploads/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "UPLOAD_TOKEN_NOT_FOUND"
    token = new_link(admin)
    assert "expires_at" in admin.get(f"/api/uploads/{token}").json()
    assert admin.get(f"/api/uploads/{token}").status_code == 200  # 여러 번 불러도 된다
    expire(token)
    assert admin.get(f"/api/uploads/{token}").json()["error"]["code"] == "UPLOAD_TOKEN_EXPIRED"
    other = new_link(admin)
    presign(admin, other)
    assert admin.get(f"/api/uploads/{other}").json()["error"]["code"] == "UPLOAD_TOKEN_USED"


def test_link_works_without_login(admin):
    token = new_link(admin)
    anon = make_client()
    assert anon.get(f"/api/uploads/{token}").status_code == 200
    assert presign(anon, token).status_code == 200


def test_presign_creates_rows(admin):
    token = new_link(admin)
    r = presign(admin, token, recording_started_at="2026-09-17T00:00:00+09:00")
    assert r.status_code == 200
    url = r.json()["upload_url"]
    with get_engine().connect() as conn:
        v = conn.execute(text("SELECT id, s3_key, original_filename, size_bytes FROM videos")).one()
        agreed = conn.execute(
            text("SELECT agreement_version, requested_ip::text AS ip FROM upload_agreements")
        ).one()
    assert v.s3_key == f"videos/{v.id}/original.mp4"  # 확장자는 소문자
    assert (v.original_filename, v.size_bytes) == ("CH03.MP4", 1000)
    assert url.startswith(f"http://localhost:8000/_local/raw/{v.s3_key}?exp=")
    assert agreed.agreement_version == "2026-10-12" and agreed.ip.startswith("127.0.0.1")
    assert count("SELECT count(*) FROM upload_tokens WHERE used_at IS NOT NULL") == 1


BAD_REQUESTS = [
    ({"filename": "a.exe"}, "UNSUPPORTED_FILE_TYPE"),
    ({"filename": "noext"}, "UNSUPPORTED_FILE_TYPE"),
    ({"size_bytes": 5 * 1024**3 + 1}, "FILE_TOO_LARGE"),
    ({"size_bytes": 0}, "VALIDATION_FAILED"),
    ({"filename": ""}, "VALIDATION_FAILED"),
    ({"recording_started_at": "2026-09-17T00:00:00"}, "VALIDATION_FAILED"),
    ({"recording_started_at": "2999-01-01T00:00:00+09:00"}, "VALIDATION_FAILED"),
    ({"agreement": None}, "AGREEMENT_REQUIRED"),
    ({"agreement": {**AGREEMENT, "version": "old"}}, "AGREEMENT_REQUIRED"),
    ({"agreement": {**AGREEMENT, "confirm_signage": False}}, "AGREEMENT_REQUIRED"),
    ({"agreement": {**AGREEMENT, "confirm_reconsignment": None}}, "AGREEMENT_REQUIRED"),
]


@pytest.mark.parametrize(("override", "code"), BAD_REQUESTS)
def test_presign_rejects_without_consuming_link(admin, override, code):
    token = new_link(admin)
    r = presign(admin, token, **override)
    assert r.status_code == 422 and r.json()["error"]["code"] == code
    assert count("SELECT count(*) FROM videos") == 0
    assert admin.get(f"/api/uploads/{token}").status_code == 200  # 다시 시도할 수 있다


def test_presign_link_errors(admin):
    assert presign(admin, "nope").json()["error"]["code"] == "UPLOAD_TOKEN_NOT_FOUND"
    token = new_link(admin)
    expire(token)
    assert presign(admin, token).json()["error"]["code"] == "UPLOAD_TOKEN_EXPIRED"
    used = new_link(admin)
    assert presign(admin, used).status_code == 200
    r = presign(admin, used)
    assert r.status_code == 410 and r.json()["error"]["code"] == "UPLOAD_TOKEN_USED"
    expire(used)  # 사용됨과 만료가 둘 다면 사용됨을 준다
    assert presign(admin, used).json()["error"]["code"] == "UPLOAD_TOKEN_USED"
    assert count("SELECT count(*) FROM videos") == 1


def test_double_presign_only_one_wins(admin):
    token = new_link(admin)
    with ThreadPoolExecutor(2) as pool:
        codes = sorted(pool.map(lambda _: presign(make_client(), token).status_code, range(2)))
    assert codes == [200, 410]
    assert count("SELECT count(*) FROM videos") == 1
    assert count("SELECT count(*) FROM upload_agreements") == 1


def test_complete_before_presign_is_conflict(admin):
    token = new_link(admin)
    r = admin.post(f"/api/uploads/{token}/complete")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"
    assert admin.post("/api/uploads/nope/complete").status_code == 404


def test_complete_queues_one_job_even_if_called_twice(admin):
    token = new_link(admin)
    presign(admin, token)
    assert admin.post(f"/api/uploads/{token}/complete").status_code == 204
    assert admin.post(f"/api/uploads/{token}/complete").status_code == 204
    with get_engine().connect() as conn:
        job = conn.execute(text("SELECT id, status FROM analysis_jobs")).one()
    assert job.status == "queued"
    files = queue_files()
    assert len(files) == 1 and files[0].name.endswith(f"-{job.id}-stage1.json")
    assert json.loads(files[0].read_text()) == {"job_id": job.id, "kind": "stage1"}
    assert count("SELECT count(*) FROM videos WHERE upload_completed_at IS NOT NULL") == 1


def test_complete_ignores_link_expiry(admin):
    token = new_link(admin)
    presign(admin, token)
    expire(token)  # 큰 파일은 업로드 중에 링크가 만료될 수 있다
    assert admin.post(f"/api/uploads/{token}/complete").status_code == 204


def test_complete_rolls_back_if_queue_fails(admin, monkeypatch):
    from app import jobs

    def boom(*_):
        raise RuntimeError("queue down")

    monkeypatch.setattr(jobs, "send_job", boom)
    token = new_link(admin)
    presign(admin, token)
    r = make_client(raise_server_exceptions=False).post(f"/api/uploads/{token}/complete")
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert count("SELECT count(*) FROM analysis_jobs") == 0
    assert count("SELECT count(*) FROM videos WHERE upload_completed_at IS NOT NULL") == 0
    monkeypatch.undo()
    assert admin.post(f"/api/uploads/{token}/complete").status_code == 204  # 다시 부르면 된다


def test_warmup(admin, monkeypatch):
    from app import jobs

    calls = []
    monkeypatch.setattr(jobs, "start_gpu", lambda: calls.append(1))
    assert admin.post("/api/uploads/nope/warmup").status_code == 404
    token = new_link(admin)
    assert admin.post(f"/api/uploads/{token}/warmup").status_code == 409
    presign(admin, token)
    assert admin.post(f"/api/uploads/{token}/warmup").status_code == 204
    assert len(calls) == 1
    admin.post(f"/api/uploads/{token}/complete")
    calls.clear()
    assert admin.post(f"/api/uploads/{token}/warmup").status_code == 204
    assert calls == []  # 작업이 생긴 뒤에는 켜지 않는다 (D-62)


def test_storage_sign_is_bound_to_key_and_method():
    exp = 9999999999
    sig = storage._signature("PUT", "raw", "videos/1/original.mp4", exp)
    assert storage.verify_local_signature("PUT", "raw", "videos/1/original.mp4", exp, sig)
    assert not storage.verify_local_signature("PUT", "raw", "videos/2/original.mp4", exp, sig)
    assert not storage.verify_local_signature("GET", "raw", "videos/1/original.mp4", exp, sig)
    assert not storage.verify_local_signature("PUT", "raw", "videos/1/original.mp4", exp + 1, sig)
    assert not storage.verify_local_signature("PUT", "raw", "videos/1/original.mp4", 1, sig)
