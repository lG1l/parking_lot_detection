import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from app import storage
from app.db import get_engine
from tests.conftest import STORAGE, make_client
from tests.test_auth import count, make_user

AGREEMENT = {
    "version": "2026-11-01",
    "confirm_signage": True,
    "confirm_disclosure_judged": True,
    "confirm_reconsignment": True,
}
BODY = {"filename": "CH03.MP4", "size_bytes": 1000, "agreement": AGREEMENT}


def login(login_id, role):
    make_user(login_id=login_id, role=role)
    c = make_client()
    r = c.post("/api/auth/login", json={"login_id": login_id, "password": "demo-password"})
    assert r.status_code == 200
    return c


def new_case(admin, victim_login_id="victim1"):
    r = admin.post("/api/cases", json={"victim_login_id": victim_login_id})
    assert r.status_code == 201
    return r.json()["id"]


@pytest.fixture
def admin():
    c = login("admin1", "admin")
    make_user(login_id="victim1", role="victim")
    return c


@pytest.fixture
def case_id(admin):
    return new_case(admin)


def presign(client, case_id, **override):
    return client.post(f"/api/cases/{case_id}/uploads/presign", json={**BODY, **override})


def new_video(admin, case_id):
    r = presign(admin, case_id)
    assert r.status_code == 200
    return r.json()["video_id"]


def queue_files():
    queue = STORAGE / "scratch" / "backend" / "queue"
    return sorted(queue.glob("*.json")) if queue.exists() else []


def test_upload_apis_require_login(client):
    for r in [
        presign(client, 1),
        client.post("/api/videos/1/upload/complete"),
        client.post("/api/videos/1/upload/warmup"),
    ]:
        assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_victim_cannot_upload(admin, case_id):
    video_id = new_video(admin, case_id)
    victim = make_client()
    victim.post("/api/auth/login", json={"login_id": "victim1", "password": "demo-password"})
    for r in [
        presign(victim, case_id),
        victim.post(f"/api/videos/{video_id}/upload/complete"),
        victim.post(f"/api/videos/{video_id}/upload/warmup"),
    ]:
        assert r.status_code == 403 and r.json()["error"]["code"] == "ROLE_NOT_ALLOWED"


def test_presign_creates_rows(admin, case_id):
    r = presign(admin, case_id, recording_started_at="2026-09-17T00:00:00+09:00")
    assert r.status_code == 200
    body = r.json()
    with get_engine().connect() as conn:
        v = conn.execute(
            text("SELECT id, case_id, s3_key, original_filename, size_bytes FROM videos")
        ).one()
        agreed = conn.execute(
            text(
                "SELECT video_id, agreement_version, requested_ip::text AS ip "
                "FROM upload_agreements"
            )
        ).one()
    assert body["video_id"] == v.id and v.case_id == case_id
    assert v.s3_key == f"videos/{v.id}/original.mp4"  # 확장자는 소문자
    assert (v.original_filename, v.size_bytes) == ("CH03.MP4", 1000)
    assert body["upload_url"].startswith(f"http://localhost:8000/_local/raw/{v.s3_key}?exp=")
    assert agreed.video_id == v.id and agreed.agreement_version == "2026-11-01"
    assert agreed.ip.startswith("127.0.0.1")


def test_presign_again_makes_new_video(admin, case_id):
    first = new_video(admin, case_id)
    second = new_video(admin, case_id)  # 끊긴 업로드는 6번부터 다시 (5.4)
    assert first != second
    assert count("SELECT count(*) FROM upload_agreements") == 2


def test_presign_other_admins_case_is_404(admin, case_id):
    other = login("admin2", "admin")
    for cid in [case_id, 999]:
        r = presign(other, cid)
        assert r.status_code == 404 and r.json()["error"]["code"] == "CASE_NOT_FOUND"
    assert count("SELECT count(*) FROM videos") == 0


BAD_REQUESTS = [
    ({"filename": "a.exe"}, "UNSUPPORTED_FILE_TYPE"),
    ({"filename": "noext"}, "UNSUPPORTED_FILE_TYPE"),
    ({"size_bytes": 5 * 1024**3 + 1}, "FILE_TOO_LARGE"),
    ({"size_bytes": 0}, "VALIDATION_FAILED"),
    ({"filename": ""}, "VALIDATION_FAILED"),
    ({"filename": "a\u0000b.mp4"}, "VALIDATION_FAILED"),
    ({"recording_started_at": "2026-09-17T00:00:00"}, "VALIDATION_FAILED"),
    ({"recording_started_at": "2999-01-01T00:00:00+09:00"}, "VALIDATION_FAILED"),
    ({"agreement": None}, "AGREEMENT_REQUIRED"),
    ({"agreement": {**AGREEMENT, "version": "2026-10-12"}}, "AGREEMENT_REQUIRED"),
    ({"agreement": {**AGREEMENT, "confirm_signage": False}}, "AGREEMENT_REQUIRED"),
    ({"agreement": {**AGREEMENT, "confirm_reconsignment": None}}, "AGREEMENT_REQUIRED"),
]


@pytest.mark.parametrize(("override", "code"), BAD_REQUESTS)
def test_presign_rejects_without_rows(admin, case_id, override, code):
    r = presign(admin, case_id, **override)
    assert r.status_code == 422 and r.json()["error"]["code"] == code
    assert count("SELECT count(*) FROM videos") == 0
    assert count("SELECT count(*) FROM upload_agreements") == 0


def test_complete_queues_one_job_even_if_called_twice(admin, case_id):
    video_id = new_video(admin, case_id)
    assert admin.post(f"/api/videos/{video_id}/upload/complete").status_code == 204
    assert admin.post(f"/api/videos/{video_id}/upload/complete").status_code == 204
    with get_engine().connect() as conn:
        job = conn.execute(text("SELECT id, video_id, status FROM analysis_jobs")).one()
    assert (job.video_id, job.status) == (video_id, "queued")
    files = queue_files()
    assert len(files) == 1 and files[0].name.endswith(f"-{job.id}-stage1.json")
    assert json.loads(files[0].read_text()) == {"job_id": job.id, "kind": "stage1"}
    assert count("SELECT count(*) FROM videos WHERE upload_completed_at IS NOT NULL") == 1


def test_concurrent_complete_makes_one_job(admin, case_id):
    video_id = new_video(admin, case_id)
    clients = [make_client(), make_client()]
    for c in clients:
        c.post("/api/auth/login", json={"login_id": "admin1", "password": "demo-password"})
    with ThreadPoolExecutor(2) as pool:
        codes = list(
            pool.map(
                lambda c: c.post(f"/api/videos/{video_id}/upload/complete").status_code, clients
            )
        )
    assert codes == [204, 204]
    assert count("SELECT count(*) FROM analysis_jobs") == 1


def test_complete_rolls_back_if_queue_fails(admin, case_id, monkeypatch):
    from app import jobs

    def boom(*_):
        raise RuntimeError("queue down")

    video_id = new_video(admin, case_id)
    monkeypatch.setattr(jobs, "send_job", boom)
    c = make_client(raise_server_exceptions=False)
    c.post("/api/auth/login", json={"login_id": "admin1", "password": "demo-password"})
    r = c.post(f"/api/videos/{video_id}/upload/complete")
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert count("SELECT count(*) FROM analysis_jobs") == 0
    assert count("SELECT count(*) FROM videos WHERE upload_completed_at IS NOT NULL") == 0
    monkeypatch.undo()
    assert admin.post(f"/api/videos/{video_id}/upload/complete").status_code == 204


def test_other_admins_video_is_404(admin, case_id):
    video_id = new_video(admin, case_id)
    other = login("admin2", "admin")
    for vid in [video_id, 999]:
        for path in ["complete", "warmup"]:
            r = other.post(f"/api/videos/{vid}/upload/{path}")
            assert r.status_code == 404 and r.json()["error"]["code"] == "VIDEO_NOT_FOUND"
    assert count("SELECT count(*) FROM analysis_jobs") == 0


def test_warmup(admin, case_id, monkeypatch):
    from app import jobs

    calls = []
    monkeypatch.setattr(jobs, "start_gpu", lambda: calls.append(1))
    video_id = new_video(admin, case_id)
    assert admin.post(f"/api/videos/{video_id}/upload/warmup").status_code == 204
    assert len(calls) == 1
    admin.post(f"/api/videos/{video_id}/upload/complete")
    calls.clear()
    assert admin.post(f"/api/videos/{video_id}/upload/warmup").status_code == 204
    assert calls == []  # 작업이 생긴 뒤에는 켜지 않는다 (D-62)


def test_storage_sign_is_bound_to_key_and_method():
    exp = 9999999999
    sig = storage._signature("PUT", "raw", "videos/1/original.mp4", exp)
    assert storage.verify_local_signature("PUT", "raw", "videos/1/original.mp4", exp, sig)
    assert not storage.verify_local_signature("PUT", "raw", "videos/2/original.mp4", exp, sig)
    assert not storage.verify_local_signature("GET", "raw", "videos/1/original.mp4", exp, sig)
    assert not storage.verify_local_signature("PUT", "raw", "videos/1/original.mp4", exp + 1, sig)
    assert not storage.verify_local_signature("PUT", "raw", "videos/1/original.mp4", 1, sig)
