import json

import pytest
from sqlalchemy import text

from app.db import get_engine
from tests.conftest import make_client
from tests.test_auth import make_user


def sql(query, **params):
    with get_engine().begin() as conn:
        return conn.execute(text(query), params)


def user_id(login_id):
    return sql("SELECT id FROM users WHERE login_id = :l", l=login_id).scalar_one()


def setup_case(admin="admin1", victim="victim1"):
    """관리자·피해자 계정과 둘을 묶은(수락까지 한) 사건을 만들고 사건 번호를 준다."""
    return sql(
        "INSERT INTO cases (admin_user_id, victim_user_id, accepted_at) "
        "VALUES (:a, :v, now()) RETURNING id",
        a=make_user(login_id=admin, role="admin"),
        v=make_user(login_id=victim, role="victim"),
    ).scalar_one()


def sign_in(client, login_id):
    r = client.post("/api/auth/login", json={"login_id": login_id, "password": "demo-password"})
    assert r.status_code == 200
    return client


@pytest.fixture
def case():
    return setup_case()


@pytest.fixture
def admin(client, case):
    return sign_in(client, "admin1")


@pytest.fixture
def victim(case):
    return sign_in(make_client(), "victim1")


def add_video(
    case_id, name="a.mp4", status=None, completed_days_ago=0, created_minutes_ago=0, **job
):
    """영상 행을 직접 만든다. status가 있으면 업로드를 마친 영상이고 작업 행도 만든다.
    열람 API(12·13·14·15·17번)를 바로 부를 수 있게 관리·감독 안내 동의도 1행 남긴다 (D-205)."""
    video_id = sql(
        "INSERT INTO videos (case_id, s3_key, original_filename, created_at, "
        "upload_completed_at) VALUES (:c, 'k', :n, now() - make_interval(mins => :m), "
        "CASE WHEN CAST(:s AS text) IS NULL THEN NULL ELSE now() - make_interval(days => :d) END) "
        "RETURNING id",
        c=case_id,
        n=name,
        m=created_minutes_ago,
        s=status,
        d=completed_days_ago,
    ).scalar_one()
    sql(
        "INSERT INTO viewing_agreements (video_id, user_id, requested_ip) "
        "SELECT :v, admin_user_id, '127.0.0.1' FROM cases WHERE id = :c",
        v=video_id,
        c=case_id,
    )
    if status is None:
        return video_id, None
    job_id = sql(
        "INSERT INTO analysis_jobs (video_id, status, failure_kind, user_retry_count, "
        "input_completed_at) VALUES (:v, :s, :f, :r, CASE WHEN :i THEN now() END) RETURNING id",
        v=video_id,
        s=status,
        f=job.get("failure_kind"),
        r=job.get("retries", 0),
        i=job.get("input_done", False),
    ).scalar_one()
    return video_id, job_id


def add_still(job_id, video_id, detections=None):
    detections = (
        [{"det_id": 1, "bbox": [1, 2, 3, 4], "conf": 0.9, "polygon": [[1, 2], [3, 2], [3, 4]]}]
        if detections is None
        else detections
    )
    sql(
        "INSERT INTO still_frames (analysis_job_id, t_sec, masked_s3_key, detections) "
        "VALUES (:j, 0.0, :k, CAST(:d AS jsonb))",
        j=job_id,
        k=f"videos/{video_id}/stills/0.jpg",
        d=json.dumps(detections),
    )


# ---- 8번 목록 ----


def test_list_requires_login(client):
    assert client.get("/api/videos").status_code == 401


def test_list_only_my_cases_newest_first(admin, victim, case):
    add_video(case, "old.mp4", "finished", created_minutes_ago=300)
    add_video(case, "new.mp4", "queued", created_minutes_ago=5)
    add_video(setup_case("admin2", "victim2"), "theirs.mp4", "queued")
    for client in (admin, victim):
        body = client.get("/api/videos").json()
        assert [v["original_filename"] for v in body] == ["new.mp4", "old.mp4"]
        assert (body[0]["status"], body[0]["case_id"]) == ("queued", case)


def test_list_computed_statuses_and_expiry(admin, case):
    me = case
    add_video(me, "up.mp4", created_minutes_ago=5)  # 작업 행 없음, 30분 안
    add_video(me, "failed-upload.mp4", created_minutes_ago=31)
    add_video(me, "done.mp4", "queued", completed_days_ago=2)
    by_name = {v["original_filename"]: v for v in admin.get("/api/videos").json()}
    assert by_name["up.mp4"]["status"] == "uploading"
    assert by_name["up.mp4"]["view_expires_at"] is None
    assert by_name["failed-upload.mp4"]["status"] == "upload_failed"
    assert by_name["done.mp4"]["view_expires_at"].endswith("+09:00")


def test_masked_deleted_counts_expired_before_purge(admin, case):
    """열람기한이 지났으면 파기 작업 전이어도 8·9번 모두 true (D-187)"""
    me = case
    fresh, _ = add_video(me, "fresh.mp4", "finished", completed_days_ago=2)
    late, _ = add_video(me, "late.mp4", "finished", completed_days_ago=31)
    purged, _ = add_video(me, "purged.mp4", "finished", completed_days_ago=2)
    sql("UPDATE videos SET masked_deleted_at = now() WHERE id = :v", v=purged)
    up = add_video(me, "up.mp4", created_minutes_ago=5)[0]  # 업로드 완료 전
    by_name = {v["original_filename"]: v for v in admin.get("/api/videos").json()}
    assert {n: v["masked_deleted"] for n, v in by_name.items()} == {
        "fresh.mp4": False,
        "late.mp4": True,
        "purged.mp4": True,
        "up.mp4": False,
    }
    for vid, expected in ((fresh, False), (late, True), (purged, True), (up, False)):
        assert admin.get(f"/api/videos/{vid}").json()["masked_deleted"] is expected


# ---- 9번 상태 ----


def test_detail_not_found_for_missing_and_foreign(admin, victim):
    foreign, _ = add_video(setup_case("admin2", "victim2"), status="queued")
    for vid in (foreign, 9999):
        for client in (admin, victim):
            r = client.get(f"/api/videos/{vid}")
            assert r.status_code == 404
            assert r.json()["error"]["code"] == "VIDEO_NOT_FOUND"
        # 역할보다 사건 소속을 먼저 본다: 관리자도 403이 아니라 404
        assert admin.get(f"/api/videos/{vid}/still").status_code == 404


def test_victim_detail_has_progress_and_failure_but_no_candidates(victim, case):
    exhausted, _ = add_video(case, status="exhausted")
    failed, _ = add_video(case, status="failed", failure_kind="vlm_outage")
    body = victim.get(f"/api/videos/{exhausted}").json()
    assert body["status"] == "exhausted"
    assert {"candidate_total", "candidate_unavailable"}.isdisjoint(body)
    body = victim.get(f"/api/videos/{failed}").json()
    assert (body["error_kind"], body["can_retry"], body["retry_left"]) == ("temporary", True, 3)


def test_still_is_victim_only(admin, case):
    vid, job = add_video(case, status="stage1_done")
    add_still(job, vid)
    r = admin.get(f"/api/videos/{vid}/still")
    assert (r.status_code, r.json()["error"]["code"]) == (403, "ROLE_NOT_ALLOWED")


def test_queue_ahead_counts_earlier_jobs(admin, case):
    me = case
    add_video(me, status="queued", created_minutes_ago=30)
    add_video(me, status="stills_running", created_minutes_ago=20)
    mine, _ = add_video(me, status="queued", created_minutes_ago=10)
    add_video(me, status="queued", created_minutes_ago=1)  # 나보다 늦게 섰다
    body = admin.get(f"/api/videos/{mine}").json()
    assert body["queue_ahead"] == 2
    assert body["input_done"] is False
    assert {"error_kind", "can_retry", "candidate_total"}.isdisjoint(body)


def test_queue_ahead_only_when_waiting(admin, case):
    me = case
    waiting, _ = add_video(me, status="stage1_done", input_done=True)
    not_yet, _ = add_video(me, status="stage1_done")
    running, _ = add_video(me, status="stills_running")
    assert admin.get(f"/api/videos/{waiting}").json()["queue_ahead"] == 0
    assert "queue_ahead" not in admin.get(f"/api/videos/{not_yet}").json()
    assert "queue_ahead" not in admin.get(f"/api/videos/{running}").json()


def test_exhausted_reports_candidate_counts(admin, case):
    me = case
    vid, job = add_video(me, status="exhausted")
    assert admin.get(f"/api/videos/{vid}").json()["candidate_total"] == 0
    for verdict in ("not_found", "unavailable", "unavailable"):
        sql(
            "INSERT INTO candidates (analysis_job_id, judged_at_sec, channel, rule_name, track_id, verdict) "
            "VALUES (:j, 1, 'A', 'r', 1, :v)",
            j=job,
            v=verdict,
        )
    body = admin.get(f"/api/videos/{vid}").json()
    assert (body["candidate_total"], body["candidate_unavailable"]) == (3, 2)


@pytest.mark.parametrize(
    ("failure_kind", "retries", "days_ago", "kind", "can_retry", "retry_left"),
    [
        ("input_error", 0, 0, "file", False, 3),
        ("input_error", 0, 40, "file", False, 3),  # 파일 문제가 만료보다 먼저
        ("vlm_outage", 0, 0, "temporary", True, 3),
        ("vlm_outage", 3, 0, "temporary", False, 0),
        ("vlm_outage", 0, 31, "expired", False, 3),
        ("vlm_parse_rate", 1, 0, "service", True, 2),
        ("worker_died", 3, 0, "service", False, 0),
    ],
)
def test_failed_error_kind(
    admin, case, failure_kind, retries, days_ago, kind, can_retry, retry_left
):
    vid, _ = add_video(
        case,
        status="failed",
        failure_kind=failure_kind,
        retries=retries,
        completed_days_ago=days_ago,
    )
    body = admin.get(f"/api/videos/{vid}").json()
    assert (body["error_kind"], body["can_retry"], body["retry_left"]) == (
        kind,
        can_retry,
        retry_left,
    )
    assert "error_message" not in body


def test_failed_with_deleted_raw_is_expired(admin, case):
    vid, _ = add_video(case, status="failed", failure_kind="vlm_outage")
    sql("UPDATE videos SET raw_deleted_at = now() WHERE id = :v", v=vid)
    body = admin.get(f"/api/videos/{vid}").json()
    assert (body["error_kind"], body["can_retry"], body["raw_deleted"]) == ("expired", False, True)


# ---- 10번 정지 장면 ----


def test_still_not_ready_states(victim, case):
    me = case
    uploading, _ = add_video(me)
    queued, _ = add_video(me, status="queued")
    for vid in (uploading, queued):
        r = victim.get(f"/api/videos/{vid}/still")
        assert (r.status_code, r.json()["error"]["code"]) == (409, "INVALID_STATE")


def test_still_expired_checked_before_missing(victim, case):
    me = case
    old, _ = add_video(me, status="queued", completed_days_ago=31)  # 장면도 없다
    deleted, _ = add_video(me, status="finished")
    sql("UPDATE videos SET masked_deleted_at = now() WHERE id = :v", v=deleted)
    for vid in (old, deleted):
        r = victim.get(f"/api/videos/{vid}/still")
        assert (r.status_code, r.json()["error"]["code"]) == (409, "MASKED_EXPIRED")


def test_still_ok_hides_conf_and_url_works(victim, case, tmp_path):
    from tests.conftest import STORAGE

    vid, job = add_video(case, status="stage1_done")
    add_still(
        job,
        vid,
        [{"det_id": 1, "bbox": [1, 2, 3, 4], "conf": 0.9, "polygon": [[1, 2], [3, 2], [3, 4]]}],
    )
    path = STORAGE / "masked" / f"videos/{vid}/stills/0.jpg"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"0123456789")
    body = victim.get(f"/api/videos/{vid}/still").json()
    assert body["detections"] == [
        {"det_id": 1, "bbox": [1, 2, 3, 4], "polygon": [[1, 2], [3, 2], [3, 4]]}
    ]
    assert body["t_sec"] == 0.0
    url = body["image_url"].removeprefix("http://localhost:8000")
    r = victim.get(url)
    assert (r.status_code, r.content) == (200, b"0123456789")
    ranged = victim.get(url, headers={"Range": "bytes=2-4"})
    assert (ranged.status_code, ranged.content) == (206, b"234")


def test_still_empty_detections_is_200(victim, case):
    vid, job = add_video(case, status="stage1_done")
    add_still(job, vid, [])
    r = victim.get(f"/api/videos/{vid}/still")
    assert (r.status_code, r.json()["detections"]) == (200, [])


# ---- /_local/masked ----


def test_masked_route_rejects_bad_signature_and_raw(admin):
    from app import storage
    from tests.conftest import STORAGE

    (STORAGE / "masked/videos/1").mkdir(parents=True)
    (STORAGE / "masked/videos/1/a.jpg").write_bytes(b"x")
    (STORAGE / "raw/videos/1").mkdir(parents=True)
    (STORAGE / "raw/videos/1/original.mp4").write_bytes(b"secret")
    url = storage.make_view_url("videos/1/a.jpg", _soon())
    assert admin.get(url.replace("http://localhost:8000", "")).status_code == 200
    assert admin.get(url.replace("http://localhost:8000", "")[:-3] + "000").status_code == 403
    # 다른 영역의 서명은 쓸 수 없다 (raw를 읽는 라우트도 없다)
    assert admin.get("/_local/raw/videos/1/original.mp4").status_code == 405


def test_masked_path_cannot_escape_area():
    # HTTP 클라이언트가 ../를 미리 정리해서, 라우트가 쓰는 함수를 직접 확인한다
    from app import local_routes
    from app.errors import ApiError

    with pytest.raises(ApiError) as caught:
        local_routes._area_path("masked", "../raw/videos/1/original.mp4")
    assert caught.value.status == 403


def test_masked_route_rejects_expired_signature(admin):
    import time

    from app import storage

    exp = int(time.time()) - 1
    sig = storage._signature("GET", "masked", "videos/1/a.jpg", exp)
    assert admin.get(f"/_local/masked/videos/1/a.jpg?exp={exp}&sig={sig}").status_code == 403


def _soon():
    from datetime import datetime, timedelta

    return datetime.now().astimezone() + timedelta(days=1)


def test_view_url_is_capped_by_view_expiry():
    from datetime import datetime, timedelta

    from app import storage

    short = datetime.now().astimezone() + timedelta(seconds=60)
    exp = int(storage.make_view_url("k", short).split("exp=")[1].split("&")[0])
    assert exp - datetime.now().timestamp() <= 61


# ---- 열람 기록 (05장 5.1) ----


def logs():
    return [tuple(r) for r in sql("SELECT action, user_id, video_id FROM access_logs ORDER BY id")]


def test_still_view_is_logged_only_on_success(victim, case):
    vid, job = add_video(case, status="stage1_done")
    victim.get(f"/api/videos/{vid}/still")  # 409, 장면이 없다
    assert [a for a, *_ in logs() if a == "view_still"] == []
    add_still(job, vid)
    victim.get(f"/api/videos/{vid}/still")
    assert ("view_still", user_id("victim1"), vid) in logs()
