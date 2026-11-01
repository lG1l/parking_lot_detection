import threading

import pytest

from local import fake_worker
from tests.conftest import make_client
from tests.test_batches import batch, make_ready, nxt
from tests.test_input import login_again
from tests.test_uploads import new_link, presign
from tests.test_videos import add_video, sql


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(fake_worker, "STEP_SECONDS", 0)


@pytest.fixture
def me(client):
    from tests.test_uploads import login
    from tests.test_videos import user_id

    login(client)
    return user_id()


def pin(client, vid, clip_id):
    return client.post(f"/api/videos/{vid}/pin", json={"candidate_clip_id": clip_id})


def pinned(client, vid):
    return client.get(f"/api/videos/{vid}/pin")


def unpin(client, vid, clip_id):
    return client.delete(f"/api/videos/{vid}/pin/{clip_id}")


def finish(client, vid):
    return client.post(f"/api/videos/{vid}/finish")


def clip_ids(client, vid, **query):
    return [c["candidate_clip_id"] for c in batch(client, vid, **query).json()["candidates"]]


def count(table_where):
    return sql(f"SELECT count(*) FROM {table_where}").scalar_one()  # noqa: S608 - 테스트 상수


# ---- API 14 ----


def test_pin_returns_pinned_list_and_logs_once(client, me):
    vid, _ = make_ready(me)
    first = clip_ids(client, vid)[0]
    r = pin(client, vid, first)
    assert r.status_code == 200
    body = r.json()
    assert [p["candidate_clip_id"] for p in body] == [first]
    assert body[0]["start_sec"] == 585.0 and body[0]["end_sec"] == 615.0
    assert body[0]["est_start_at"] is None and body[0]["est_end_at"] is None
    assert body[0]["clip_url"] and body[0]["pinned_at"]
    assert count("access_logs WHERE action = 'pin_incident'") == 1
    assert sql("SELECT status FROM analysis_jobs").scalar_one() == "ready"  # 상태를 바꾸지 않는다


def test_pin_same_clip_twice_is_200_with_one_row_and_one_log(client, me):
    vid, _ = make_ready(me)
    first = clip_ids(client, vid)[0]
    assert pin(client, vid, first).status_code == 200
    r = pin(client, vid, first)
    assert r.status_code == 200 and len(r.json()) == 1
    assert count("pinned_incidents") == 1
    assert count("access_logs WHERE action = 'pin_incident'") == 1


def test_pin_keeps_pin_order_and_estimates_times(client, me):
    vid, _ = make_ready(me)
    sql("UPDATE videos SET recording_started_at = '2026-09-17 03:00:00+09' WHERE id = :v", v=vid)
    first, second, _ = clip_ids(client, vid)
    pin(client, vid, second)
    body = pin(client, vid, first).json()
    assert [p["candidate_clip_id"] for p in body] == [second, first]
    assert body[1]["est_start_at"] == "2026-09-17T03:09:45+09:00"
    assert body[1]["est_end_at"] == "2026-09-17T03:10:15+09:00"


def test_pin_logs_view_clip_per_clip_in_response(client, me):
    vid, _ = make_ready(me)
    first, second, _ = clip_ids(client, vid)
    sql("DELETE FROM access_logs")
    pin(client, vid, first)
    pin(client, vid, second)
    assert count("access_logs WHERE action = 'view_clip'") == 3  # 1개 + 2개


def test_pin_works_for_previous_batch_clip_and_while_batch_running(client, me):
    vid, _ = make_ready(me, "many")
    old = clip_ids(client, vid)[0]
    nxt(client, vid, "main", 1)
    sql("UPDATE analysis_jobs SET status = 'batch_running'")
    assert pin(client, vid, old).status_code == 200  # verdict가 not_found여도 막지 않는다


def test_pin_rejects_foreign_missing_and_unfinished_clips(client, me):
    vid, job = make_ready(me)
    make_ready(me)
    foreign = sql(
        "SELECT c.id FROM candidate_clips c JOIN candidates d ON d.id = c.candidate_id "
        "WHERE d.analysis_job_id != :j LIMIT 1",
        j=job,
    ).scalar_one()
    mine = clip_ids(client, vid)[0]
    for clip_id in (foreign, 999999):
        r = pin(client, vid, clip_id)
        assert r.status_code == 404 and r.json()["error"]["code"] == "CLIP_NOT_FOUND"
    sql("UPDATE candidate_clips SET status = 'pending' WHERE id = :c", c=mine)
    assert pin(client, vid, mine).json()["error"]["code"] == "CLIP_NOT_FOUND"
    assert count("pinned_incidents") == 0


def test_pin_state_and_expiry_errors(client, me):
    vid, _ = make_ready(me)
    clips = clip_ids(client, vid)
    pin(client, vid, clips[0])
    assert finish(client, vid).status_code == 200
    r = pin(client, vid, clips[1])
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"
    assert pin(client, vid, clips[0]).json()["error"]["code"] == "INVALID_STATE"
    assert pin(client, 99999, 1).status_code == 404

    old, _ = make_ready(me)
    sql("UPDATE videos SET upload_completed_at = now() - interval '31 days' WHERE id = :v", v=old)
    assert pin(client, old, 1).json()["error"]["code"] == "MASKED_EXPIRED"


@pytest.mark.parametrize(
    "body", [{}, {"candidate_clip_id": "a"}, {"candidate_clip_id": 1.5}, {"x": 1}]
)
def test_pin_validation(client, me, body):
    vid, _ = make_ready(me)
    r = client.post(f"/api/videos/{vid}/pin", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_FAILED"


def test_pin_requires_login(client):
    assert pin(client, 1, 1).status_code == 401


# ---- API 15 ----


def test_get_pinned_empty_in_any_state(client, me):
    vid, _ = make_ready(me)
    assert pinned(client, vid).json() == []
    uploading, _ = add_video(me, "u.mp4")
    assert pinned(client, uploading).json() == []


def test_get_pinned_lists_and_logs_view_clip_after_finish(client, me):
    vid, _ = make_ready(me)
    first, second, _ = clip_ids(client, vid)
    pin(client, vid, first)
    pin(client, vid, second)
    finish(client, vid)
    sql("DELETE FROM access_logs")
    body = pinned(client, vid).json()
    assert [p["candidate_clip_id"] for p in body] == [first, second]
    assert count("access_logs WHERE action = 'view_clip'") == 2
    url = body[0]["clip_url"].replace("http://testserver", "")
    assert client.get(url).status_code == 200


def test_get_pinned_errors(client, me):
    old, _ = make_ready(me)
    sql("UPDATE videos SET masked_deleted_at = now() WHERE id = :v", v=old)
    r = pinned(client, old)
    assert r.status_code == 409 and r.json()["error"]["code"] == "MASKED_EXPIRED"
    assert pinned(client, 99999).status_code == 404
    assert make_client().get("/api/videos/1/pin").status_code == 401


# ---- API 17 ----


def test_finish_without_pins_is_rejected(client, me):
    vid, _ = make_ready(me)
    r = finish(client, vid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "NO_PINNED_INCIDENTS"
    assert sql("SELECT status FROM analysis_jobs").scalar_one() == "ready"


def test_finish_sets_status_and_is_not_repeatable(client, me):
    vid, _ = make_ready(me)
    pin(client, vid, clip_ids(client, vid)[0])
    assert finish(client, vid).json() == {"status": "finished"}
    assert sql("SELECT status FROM analysis_jobs").scalar_one() == "finished"
    r = finish(client, vid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"


def test_finish_while_batch_running(client, me):
    vid, _ = make_ready(me)
    pin(client, vid, clip_ids(client, vid)[0])
    sql("UPDATE analysis_jobs SET status = 'batch_running'")
    assert finish(client, vid).status_code == 200


def test_finish_state_errors(client, me):
    early, _ = add_video(me, "a.mp4", "stage1_done")
    assert finish(client, early).json()["error"]["code"] == "INVALID_STATE"
    uploading, _ = add_video(me, "b.mp4")
    assert finish(client, uploading).json()["error"]["code"] == "INVALID_STATE"
    assert finish(client, 99999).status_code == 404
    assert make_client().post("/api/videos/1/finish").status_code == 401


def test_concurrent_pin_and_finish_never_pin_after_finish(me):
    vid, _ = make_ready(me)
    clients = [login_again(make_client()) for _ in range(2)]
    first, second, _ = clip_ids(clients[0], vid)
    pin(clients[0], vid, first)
    codes = {}

    def do_pin():
        codes["pin"] = pin(clients[0], vid, second).status_code

    def do_finish():
        codes["finish"] = finish(clients[1], vid).status_code

    threads = [threading.Thread(target=do_pin), threading.Thread(target=do_finish)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert codes["finish"] == 200
    # 고정이 먼저면 포함해서 끝나고(200, 2행), 끝내기가 먼저면 거절된다(409, 1행)
    assert (codes["pin"], count("pinned_incidents")) in ((200, 2), (409, 1))


def test_other_upload_keeps_review_in_progress(client, me):
    """10장 6번: A를 확인하는 도중 B를 올리고 분석해도 A의 상태·고정·후보 판정은 그대로다."""
    vid, _ = make_ready(me)
    first = clip_ids(client, vid)[0]
    pin(client, vid, first)
    token = new_link(client)
    presign(client, token)
    assert client.post(f"/api/uploads/{token}/complete").status_code == 204
    other = sql("SELECT id FROM analysis_jobs WHERE status = 'queued'").scalar_one()
    fake_worker.Worker("normal", step=False).handle(other, "stage1")
    assert client.get(f"/api/videos/{vid}").json()["status"] == "ready"
    assert [p["candidate_clip_id"] for p in pinned(client, vid).json()] == [first]
    assert count("candidates WHERE verdict != 'unseen'") == 0


# ---- API 20 ----


def test_unpin_removes_row_returns_remaining_and_allows_repin(client, me):
    vid, _ = make_ready(me)
    first, second = clip_ids(client, vid)[:2]
    pin(client, vid, first)
    pin(client, vid, second)
    r = unpin(client, vid, first)
    assert r.status_code == 200
    assert [p["candidate_clip_id"] for p in r.json()] == [second]
    assert count("pinned_incidents") == 1
    assert client.get(f"/api/videos/{vid}").json()["status"] == "ready"
    assert pin(client, vid, first).status_code == 200  # 해제한 뒤 다시 고정할 수 있다
    assert count("pinned_incidents") == 2


def test_unpin_not_pinned_is_200(client, me):
    vid, _ = make_ready(me)
    first, second = clip_ids(client, vid)[:2]
    pin(client, vid, first)
    r = unpin(client, vid, second)
    assert r.status_code == 200 and len(r.json()) == 1
    assert unpin(client, vid, 999999).status_code == 200
    assert count("pinned_incidents") == 1


def test_unpin_to_zero_blocks_finish(client, me):
    vid, _ = make_ready(me)
    first = clip_ids(client, vid)[0]
    pin(client, vid, first)
    assert unpin(client, vid, first).json() == []
    r = finish(client, vid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "NO_PINNED_INCIDENTS"


def test_unpin_after_finish_is_409_and_keeps_row(client, me):
    vid, _ = make_ready(me)
    first = clip_ids(client, vid)[0]
    pin(client, vid, first)
    assert finish(client, vid).status_code == 200
    assert unpin(client, vid, first).json()["error"]["code"] == "INVALID_STATE"
    assert count("pinned_incidents") == 1


def test_unpin_with_other_jobs_clip_keeps_row(client, me):
    vid, _ = make_ready(me)
    other_vid, _ = make_ready(me)
    first = clip_ids(client, vid)[0]
    pin(client, vid, first)
    assert unpin(client, other_vid, first).status_code == 200  # 다른 작업의 고정은 지우지 않는다
    assert count("pinned_incidents") == 1
    assert unpin(client, 99999, first).status_code == 404


def test_unpin_expired_and_requires_login(client, me):
    old, _ = make_ready(me)
    sql("UPDATE videos SET upload_completed_at = now() - interval '31 days' WHERE id = :v", v=old)
    assert unpin(client, old, 1).json()["error"]["code"] == "MASKED_EXPIRED"
    assert make_client().delete(f"/api/videos/{old}/pin/1").status_code == 401
