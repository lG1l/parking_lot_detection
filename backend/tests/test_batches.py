import threading

import pytest

from local import fake_worker
from tests.conftest import make_client
from tests.test_fake_worker import job_row
from tests.test_input import login_again
from tests.test_uploads import login, queue_files
from tests.test_videos import add_video, sql, user_id


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(fake_worker, "STEP_SECONDS", 0)
    monkeypatch.setattr(fake_worker, "POLL_SECONDS", 0)


@pytest.fixture
def me(client):
    login(client)
    return user_id()


def make_ready(me, scenario="normal"):
    """워커가 2단계를 끝낸 영상(ready)."""
    vid, job = add_video(me, status="stage1_done", input_done=True)
    sql("UPDATE videos SET width = 1920, height = 1080 WHERE id = :v", v=vid)
    fake_worker.Worker(scenario, step=False).handle(job, "stage2")
    return vid, job


def run_next_batch(job):
    fake_worker.Worker("normal", step=False).handle(job, "next_batch")


def batch(client, vid, **query):
    return client.get(f"/api/videos/{vid}/batch", params=query)


def nxt(client, vid, kind="main", n=1):
    return client.post(f"/api/videos/{vid}/batch/next", json={"list": kind, "batch_no": n})


# ---- 워커가 만든 상태 ----


def test_worker_normal_makes_three_main_candidates(me):
    _, job = make_ready(me)
    assert job_row(job).status == "ready"
    row = sql("SELECT current_batch_no, current_failed_batch_no FROM analysis_jobs").one()
    assert tuple(row) == (1, None)
    assert sql("SELECT count(*) FROM candidate_clips WHERE status = 'done'").scalar_one() == 3


def test_worker_many_numbers_two_batches_ahead(me):
    make_ready(me, "many")
    main = sql(
        "SELECT batch_no, count(*) FROM candidates WHERE list_kind = 'main' GROUP BY batch_no "
        "ORDER BY batch_no NULLS LAST"
    ).all()
    assert [tuple(r) for r in main] == [(1, 10), (2, 10), (None, 5)]
    assert sql("SELECT current_failed_batch_no FROM analysis_jobs").scalar_one() == 1
    assert sql("SELECT count(*) FROM candidate_clips WHERE status = 'done'").scalar_one() == 23


def test_worker_next_batch_numbers_one_batch_and_is_idempotent(me):
    _, job = make_ready(me, "many")
    sql("UPDATE analysis_jobs SET current_batch_no = 2 WHERE id = :j", j=job)
    run_next_batch(job)
    assert sql("SELECT max(batch_no) FROM candidates WHERE list_kind = 'main'").scalar_one() == 3
    run_next_batch(job)  # 이미 한 묶음 앞서 있다
    assert sql("SELECT max(batch_no) FROM candidates WHERE list_kind = 'main'").scalar_one() == 3
    assert sql("SELECT count(*) FROM candidate_clips WHERE status != 'done'").scalar_one() == 0


# ---- API 12 ----


def test_get_batch_normal(client, me):
    vid, _ = make_ready(me)
    body = batch(client, vid).json()
    assert body["list"] == "main" and body["batch_no"] == 1 and body["unavailable"] == 0
    assert [c["rank"] for c in body["candidates"]] == [1, 2, 3]
    assert [c["vlm_score"] for c in body["candidates"]] == [95, 94, 93]
    assert body["lists"] == {
        "main": {"latest_batch_no": 1, "remaining": 0, "done": False, "unavailable": 0},
        "parse_failed": {"latest_batch_no": None, "remaining": 0, "done": True, "unavailable": 0},
    }
    clip = body["candidates"][0]
    assert clip["start_sec"] == 585.0 and clip["end_sec"] == 615.0
    url = clip["clip_url"].replace("http://testserver", "")
    assert client.get(url).content == fake_worker.FAKE_CLIP


def test_get_batch_logs_view_clip_per_clip(client, me):
    vid, _ = make_ready(me)
    batch(client, vid)
    batch(client, vid)
    assert sql("SELECT count(*) FROM access_logs WHERE action = 'view_clip'").scalar_one() == 6


def test_get_batch_many_summary(client, me):
    vid, _ = make_ready(me, "many")
    body = batch(client, vid).json()
    assert len(body["candidates"]) == 10
    assert body["lists"]["main"] == {
        "latest_batch_no": 1,
        "remaining": 15,
        "done": False,
        "unavailable": 0,
    }
    assert body["lists"]["parse_failed"]["latest_batch_no"] == 1
    failed = batch(client, vid, list="parse_failed").json()
    assert [c["rank"] for c in failed["candidates"]] == [1, 2, 3]
    assert all(c["vlm_score"] is None for c in failed["candidates"])


@pytest.mark.parametrize(
    "query",
    [{"list": "x"}, {"list": "parse_failed"}, {"batch_no": 2}, {"batch_no": 0}, {"batch_no": "a"}],
)
def test_get_batch_validation(client, me, query):
    vid, _ = make_ready(me)
    r = batch(client, vid, **query)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_FAILED"


def test_get_batch_state_errors(client, me):
    early, _ = add_video(me, "a.mp4", "stage1_done")
    assert batch(client, early).json()["error"]["code"] == "INVALID_STATE"
    done, _ = add_video(me, "b.mp4", "exhausted")
    assert batch(client, done).json()["error"]["code"] == "INVALID_STATE"
    old, _ = add_video(me, "c.mp4", "ready", completed_days_ago=31)
    assert batch(client, old).json()["error"]["code"] == "MASKED_EXPIRED"
    assert batch(client, 99999).status_code == 404


def test_get_batch_requires_login(client):
    assert batch(client, 1).status_code == 401
    assert nxt(client, 1).status_code == 401


# ---- API 13 ----


def test_next_to_prepared_batch_stays_ready(client, me):
    vid, _ = make_ready(me, "many")
    r = nxt(client, vid)
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert r.json()["lists"]["main"]["latest_batch_no"] == 2
    assert r.json()["lists"]["main"]["remaining"] == 5
    assert (
        sql(
            "SELECT count(*) FROM candidates WHERE batch_no = 1 AND list_kind = 'main' "
            "AND verdict = 'not_found' AND verdict_at IS NOT NULL"
        ).scalar_one()
        == 10
    )
    assert [p.name.endswith("-next_batch.json") for p in queue_files()] == [True]


def test_full_walkthrough_ends_exhausted(client, me):
    vid, job = make_ready(me, "many")
    nxt(client, vid, "main", 1)
    run_next_batch(job)
    nxt(client, vid, "main", 2)
    run_next_batch(job)
    last = nxt(client, vid, "main", 3).json()
    assert last["status"] == "ready" and last["lists"]["main"]["done"] is True
    again = nxt(client, vid, "main", 3)  # 다 넘긴 목록에 다시 보내도 200
    assert again.status_code == 200
    final = nxt(client, vid, "parse_failed", 1).json()
    assert final["status"] == "exhausted"
    assert nxt(client, vid, "parse_failed", 1).status_code == 409


def test_next_before_batch_is_ready_goes_batch_running(client, me):
    vid, job = make_ready(me, "many")
    nxt(client, vid, "main", 1)
    r = nxt(client, vid, "main", 2).json()  # 묶음 3은 아직 번호도 없다
    assert r["status"] == "batch_running"
    assert r["lists"]["main"]["latest_batch_no"] == 2  # 만드는 중인 묶음은 뺀다
    body = batch(client, vid).json()
    assert body["batch_no"] == 2 and len(body["candidates"]) == 10
    assert nxt(client, vid, "main", 3).json()["error"]["code"] == "INVALID_STATE"
    run_next_batch(job)
    assert job_row(job).status == "ready"
    assert batch(client, vid).json()["lists"]["main"]["latest_batch_no"] == 3


def test_next_without_more_candidates_is_exhausted_for_normal(client, me):
    vid, _ = make_ready(me)
    assert nxt(client, vid).json()["status"] == "exhausted"
    assert queue_files() == []


def test_next_validation_and_state_errors(client, me):
    vid, _ = make_ready(me, "many")
    for body in (
        {},
        {"list": "main"},
        {"list": "x", "batch_no": 1},
        {"list": "main", "batch_no": 0},
    ):
        r = client.post(f"/api/videos/{vid}/batch/next", json=body)
        assert r.status_code == 422, body
    assert nxt(client, vid, "main", 2).json()["error"]["code"] == "INVALID_STATE"
    assert nxt(client, vid, "parse_failed", 2).status_code == 409
    early, _ = add_video(me, "e.mp4", "queued")
    assert nxt(client, early).json()["error"]["code"] == "INVALID_STATE"
    expired, _ = add_video(me, "x.mp4", "ready", completed_days_ago=31)
    assert nxt(client, expired).json()["error"]["code"] == "RAW_EXPIRED"
    raw_gone, _ = add_video(me, "y.mp4", "ready")
    sql("UPDATE videos SET raw_deleted_at = now() WHERE id = :v", v=raw_gone)
    assert nxt(client, raw_gone).json()["error"]["code"] == "RAW_EXPIRED"


def test_queue_failure_rolls_back_next(me, monkeypatch):
    vid, _ = make_ready(me, "many")
    client = login_again(make_client(raise_server_exceptions=False))

    def boom(*_):
        raise RuntimeError("queue down")

    monkeypatch.setattr("app.jobs.send_job", boom)
    assert nxt(client, vid).status_code == 500
    assert sql("SELECT current_batch_no FROM analysis_jobs").scalar_one() == 1
    assert sql("SELECT count(*) FROM candidates WHERE verdict = 'not_found'").scalar_one() == 0


def test_concurrent_next_yields_one_success(me):
    vid, _ = make_ready(me, "many")
    clients = [login_again(make_client()) for _ in range(2)]
    codes = []
    threads = [
        threading.Thread(target=lambda c=c: codes.append(nxt(c, vid).status_code)) for c in clients
    ]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [200, 409]
    assert sql("SELECT current_batch_no FROM analysis_jobs").scalar_one() == 2
