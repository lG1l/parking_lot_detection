import json
import logging

import pytest
from botocore.exceptions import ClientError

from app import periodic
from tests.test_uploads import admin, new_link, presign, queue_files  # noqa: F401 - admin은 fixture
from tests.test_videos import add_video, sql, user_id


@pytest.fixture
def me(client):
    from tests.test_uploads import login

    login(client)
    return user_id()


def deleted(vid):
    return sql("SELECT raw_deleted_at, masked_deleted_at FROM videos WHERE id = :v", v=vid).one()


def delete_logs():
    return sorted(
        tuple(r)
        for r in sql(
            "SELECT video_id, action, user_id, requested_ip FROM access_logs "
            "WHERE action LIKE 'delete_%'"
        )
    )


# ---- 파기 표시와 기록 (D-142) ----


def test_mark_expired_marks_and_logs_once(me):
    old, _ = add_video(me, "old.mp4", "ready", completed_days_ago=31)
    recent, _ = add_video(me, "recent.mp4", "ready", completed_days_ago=29)
    uploading, _ = add_video(me, "u.mp4")
    periodic.mark_expired()
    periodic.mark_expired()
    raw, masked = deleted(old)
    assert raw is not None and raw == masked
    assert deleted(recent) == (None, None) and deleted(uploading) == (None, None)
    assert delete_logs() == [(old, "delete_masked", None, None), (old, "delete_raw", None, None)]


def test_mark_expired_leaves_already_marked_video(me):
    vid, _ = add_video(me, "a.mp4", "finished", completed_days_ago=40)
    sql(
        "UPDATE videos SET raw_deleted_at = '2026-01-01', masked_deleted_at = '2026-01-01' "
        "WHERE id = :v",
        v=vid,
    )
    periodic.mark_expired()
    assert delete_logs() == []


def test_delete_old_agreements(admin):  # noqa: F811
    for _ in range(2):
        presign(admin, new_link(admin))
    first, second = sql("SELECT id FROM upload_agreements ORDER BY id").scalars().all()
    sql(
        "UPDATE upload_agreements SET agreed_at = now() - interval '91 days' WHERE id = :i", i=first
    )
    sql(
        "UPDATE upload_agreements SET agreed_at = now() - interval '89 days' WHERE id = :i",
        i=second,
    )
    periodic.delete_old_agreements()
    assert sql("SELECT id FROM upload_agreements").scalars().all() == [second]


# ---- 멈춘 작업 다시 넣기 (D-56, D-153) ----


def stall(job, minutes):
    sql(
        "UPDATE analysis_jobs SET updated_at = now() - make_interval(mins => :m) WHERE id = :j",
        j=job,
        m=minutes,
    )


def sent():
    return sorted(
        (m["job_id"], m["kind"]) for m in (json.loads(f.read_text()) for f in queue_files())
    )


def test_requeue_stalled_waiting_jobs_once(me):
    _, queued = add_video(me, "a.mp4", "queued")
    _, inputted = add_video(me, "b.mp4", "stage1_done", input_done=True)
    _, batch = add_video(me, "c.mp4", "batch_running")
    _, not_inputted = add_video(me, "d.mp4", "stage1_done")
    _, running = add_video(me, "e.mp4", "stage2_running")
    _, fresh = add_video(me, "f.mp4", "queued")
    for job in (queued, inputted, batch, not_inputted, running):
        stall(job, 11)
    stall(fresh, 9)
    periodic.requeue_stalled()
    periodic.requeue_stalled()  # updated_at을 찍었으므로 다시 보내지 않는다
    assert sent() == sorted([(queued, "stage1"), (inputted, "stage2"), (batch, "next_batch")])
    assert sql("SELECT status FROM analysis_jobs WHERE id = :j", j=queued).scalar_one() == "queued"


def test_requeue_send_failure_retries_next_time(me, monkeypatch):
    _, job = add_video(me, "a.mp4", "queued")
    stall(job, 11)

    def broken(*_):
        raise RuntimeError("queue down")

    monkeypatch.setattr(periodic.jobs, "send_job", broken)
    with pytest.raises(RuntimeError):
        periodic.requeue_stalled()
    monkeypatch.undo()
    periodic.requeue_stalled()  # 되돌렸으므로 다음 점검에 다시 넣는다
    assert sent() == [(job, "stage1")]


# ---- GPU 켜기 점검 (D-42) ----


class FakeEc2:
    def __init__(self, state, error=None):
        self.state, self.error, self.started = state, error, 0

    def describe_instances(self, **_):
        return {"Reservations": [{"Instances": [{"State": {"Name": self.state}}]}]}

    def start_instances(self, **_):
        if self.error:
            raise self.error
        self.started += 1


@pytest.fixture
def aws(monkeypatch):
    from app.config import get_settings

    settings = get_settings().model_copy(
        update={"app_mode": "aws", "aws_region": "ap-northeast-2", "gpu_instance_id": "i-1"}
    )
    monkeypatch.setattr(periodic, "get_settings", lambda: settings)
    ec2 = FakeEc2("stopped")
    monkeypatch.setattr(periodic.boto3, "client", lambda *_, **__: ec2)
    return ec2


def test_gpu_check_starts_only_when_jobs_wait_and_gpu_stopped(me, aws):
    check = periodic.GpuCheck()
    check.tick()
    assert aws.started == 0  # 기다리는 작업이 없다
    add_video(me, "a.mp4", "stage2_running")
    check.tick()
    assert aws.started == 1
    for state in ("pending", "running", "stopping"):
        aws.state = state
        check.tick()
    assert aws.started == 1


def test_gpu_check_folds_repeated_errors(me, aws, caplog):
    caplog.set_level(logging.INFO, "app.periodic")
    add_video(me, "a.mp4", "queued")
    aws.error = ClientError({"Error": {"Code": "IncorrectInstanceState"}}, "StartInstances")
    check = periodic.GpuCheck()
    for _ in range(3):
        check.tick()
    aws.error = None
    check.tick()
    lines = [r.getMessage() for r in caplog.records if r.name == "app.periodic"]
    assert lines == [
        "GPU start failed: IncorrectInstanceState (same error suppressed until it changes)",
        "GPU start succeeded after 3 failures",
    ]


def test_gpu_check_is_off_in_local_mode(me, monkeypatch):
    add_video(me, "a.mp4", "queued")
    monkeypatch.setattr(periodic.boto3, "client", lambda *_, **__: pytest.fail("called AWS"))
    periodic.GpuCheck().tick()


# ---- 루프 ----


def test_run_does_hourly_tasks_at_start_and_survives_failures(monkeypatch):
    calls = []

    class Stop(Exception):
        pass

    def broken():
        calls.append("mark")
        raise RuntimeError("db down")

    monkeypatch.setattr(periodic, "mark_expired", broken)
    monkeypatch.setattr(periodic, "delete_old_agreements", lambda: calls.append("agree"))
    monkeypatch.setattr(periodic, "requeue_stalled", lambda: calls.append("requeue"))
    monkeypatch.setattr(periodic.GpuCheck, "tick", lambda self: calls.append("gpu"))
    ticks = iter(range(3))

    def sleep(_):
        if next(ticks, None) is None:  # 네 번째 회차가 끝나면 멈춘다
            raise Stop

    monkeypatch.setattr(periodic.time, "sleep", sleep)
    with pytest.raises(Stop):
        periodic.run()
    # 1시간 작업은 켤 때 한 번만, 5초 작업은 회차마다. 앞 작업이 실패해도 나머지는 돈다
    assert calls == ["mark", "agree"] + ["requeue", "gpu"] * 4
