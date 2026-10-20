import json
import threading

import pytest

from local import fake_worker
from tests.conftest import make_client
from tests.test_batches import make_ready
from tests.test_input import login_again
from tests.test_uploads import login, queue_files
from tests.test_videos import add_video, sql, user_id


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(fake_worker, "STEP_SECONDS", 0)


@pytest.fixture
def me(client):
    login(client)
    return user_id()


def retry(client, vid):
    return client.post(f"/api/videos/{vid}/retry")


def fail(job, failure_kind="vlm_outage", **ended):
    """작업을 failed로 만들고 어느 단계까지 끝냈는지 정한다."""
    sql(
        "UPDATE analysis_jobs SET status = 'failed', failure_kind = :f, error_message = 'x', "
        "stage1_ended_at = CASE WHEN :s1 THEN now() END, "
        "stage2_ended_at = CASE WHEN :s2 THEN now() END WHERE id = :j",
        f=failure_kind,
        s1=ended.get("s1", False),
        s2=ended.get("s2", False),
        j=job,
    )


def queued_kinds():
    return [json.loads(f.read_text())["kind"] for f in queue_files()]


def job_state():
    return tuple(
        sql("SELECT status, user_retry_count, failure_kind, error_message FROM analysis_jobs").one()
    )


@pytest.mark.parametrize(
    ("ended", "status", "kind"),
    [
        ({}, "queued", "stage1"),
        ({"s1": True}, "stage1_done", "stage2"),
        ({"s1": True, "s2": True}, "ready", "next_batch"),
    ],
)
def test_retry_resumes_at_failed_stage(client, me, ended, status, kind):
    vid, job = add_video(me, "a.mp4", "failed", failure_kind="vlm_outage", retries=0)
    fail(job, **ended)
    r = retry(client, vid)
    assert r.status_code == 202
    assert r.json() == {"status": status, "retry_left": 2}
    assert job_state() == (status, 1, None, None)
    assert queued_kinds() == [kind]


def test_retry_goes_back_to_batch_running_when_current_batch_is_building(client, me):
    vid, job = make_ready(me)
    sql(
        "UPDATE candidate_clips SET status = 'pending' WHERE id = (SELECT min(id) FROM candidate_clips)"
    )
    fail(job, s1=True, s2=True)
    assert retry(client, vid).json()["status"] == "batch_running"
    assert queued_kinds() == ["next_batch"]


def test_retry_goes_back_to_ready_when_current_batch_is_built(client, me):
    vid, job = make_ready(me)
    fail(job, s1=True, s2=True)
    assert retry(client, vid).json()["status"] == "ready"


def test_retry_counts_down_and_stops_at_limit(client, me):
    vid, job = add_video(me, "a.mp4", "failed", failure_kind="vlm_outage")
    for left in (2, 1, 0):
        fail(job)
        assert retry(client, vid).json()["retry_left"] == left
    fail(job)
    r = retry(client, vid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "RETRY_LIMIT_REACHED"
    assert job_state()[:2] == ("failed", 3)


def test_retry_rejects_not_failed_and_duplicate(client, me):
    ok, _ = add_video(me, "a.mp4", "ready")
    assert retry(client, ok).json()["error"]["code"] == "INVALID_STATE"
    uploading, _ = add_video(me, "b.mp4")
    assert retry(client, uploading).json()["error"]["code"] == "INVALID_STATE"
    vid, job = add_video(me, "c.mp4", "failed", failure_kind="vlm_outage")
    fail(job)
    assert retry(client, vid).status_code == 202
    again = retry(client, vid)  # 응답을 못 받아 다시 보낸 요청
    assert again.status_code == 409 and again.json()["error"]["code"] == "INVALID_STATE"
    assert sql("SELECT user_retry_count FROM analysis_jobs WHERE id = :j", j=job).scalar_one() == 1
    assert retry(client, 99999).status_code == 404
    assert make_client().post("/api/videos/1/retry").status_code == 401


def test_retry_rejects_file_problem_and_expired_raw(client, me):
    vid, _ = add_video(me, "a.mp4", "failed", failure_kind="input_error")
    r = retry(client, vid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "RETRY_NOT_ALLOWED"
    old, _ = add_video(me, "b.mp4", "failed", failure_kind="vlm_outage", completed_days_ago=31)
    assert retry(client, old).json()["error"]["code"] == "RAW_EXPIRED"
    gone, _ = add_video(me, "c.mp4", "failed", failure_kind="vlm_outage")
    sql("UPDATE videos SET raw_deleted_at = now() WHERE id = :v", v=gone)
    assert retry(client, gone).json()["error"]["code"] == "RAW_EXPIRED"
    assert queue_files() == []


def test_queue_failure_rolls_back_retry(me, monkeypatch):
    vid, job = add_video(me, "a.mp4", "failed", failure_kind="vlm_outage")
    fail(job)
    client = login_again(make_client(raise_server_exceptions=False))

    def boom(*_):
        raise RuntimeError("queue down")

    monkeypatch.setattr("app.jobs.send_job", boom)
    assert retry(client, vid).status_code == 500
    assert job_state() == ("failed", 0, "vlm_outage", "x")


def test_concurrent_retry_with_one_left_accepts_one(me):
    """10장 9번: 재시도를 2번 쓴 뒤 두 요청이 동시에 와도 마지막 1번만 접수한다."""
    vid, job = add_video(me, "a.mp4", "failed", failure_kind="vlm_outage", retries=2)
    fail(job)
    clients = [login_again(make_client()) for _ in range(2)]
    codes = []
    threads = [
        threading.Thread(target=lambda c=c: codes.append(retry(c, vid).status_code))
        for c in clients
    ]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [202, 409]
    assert job_state()[:2] == ("queued", 3)
    assert queued_kinds() == ["stage1"]
