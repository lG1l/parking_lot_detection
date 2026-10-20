import json
import sys

import pytest

from local import fake_worker
from tests.conftest import STORAGE
from tests.test_uploads import login
from tests.test_videos import add_video, sql, user_id


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(fake_worker, "STEP_SECONDS", 0)
    monkeypatch.setattr(fake_worker, "POLL_SECONDS", 0)


@pytest.fixture
def me(client):
    login(client)
    return user_id()


def job_row(job_id):
    return sql(
        "SELECT status, failure_kind, user_retry_count FROM analysis_jobs WHERE id = :j", j=job_id
    ).one()


def run(scenario, job_id, kind):
    return fake_worker.Worker(scenario, step=False).handle(job_id, kind)


def test_stage1_normal_writes_still_and_detections(me):
    vid, job = add_video(me, status="queued")
    assert run("normal", job, "stage1") is True
    assert job_row(job).status == "stage1_done"
    still = sql(
        "SELECT masked_s3_key, detections FROM still_frames WHERE analysis_job_id = :j", j=job
    ).one()
    assert (STORAGE / "masked" / still.masked_s3_key).is_file()
    assert len(still.detections) == 2
    assert sql("SELECT width FROM videos WHERE id = :v", v=vid).scalar_one() == 1920


def test_stage1_no_vehicles_has_empty_detections(me):
    _, job = add_video(me, status="queued")
    run("no_vehicles", job, "stage1")
    assert sql("SELECT detections FROM still_frames").scalar_one() == []


@pytest.mark.parametrize(
    ("scenario", "kind"),
    [("input_error", "input_error"), ("stage1_fail_always", "worker_died")],
)
def test_stage1_failures(me, scenario, kind):
    _, job = add_video(me, status="queued")
    run(scenario, job, "stage1")
    row = job_row(job)
    assert (row.status, row.failure_kind) == ("failed", kind)
    assert sql("SELECT count(*) FROM still_frames").scalar_one() == 0


def test_fail_once_fails_only_before_retry(me):
    _, first = add_video(me, status="queued")
    run("stage1_fail_once", first, "stage1")
    assert job_row(first).status == "failed"
    _, retried = add_video(me, status="queued", retries=1)
    run("stage1_fail_once", retried, "stage1")
    assert job_row(retried).status == "stage1_done"


def test_stage1_ignores_jobs_in_other_states(me):
    _, job = add_video(me, status="finished")
    assert run("normal", job, "stage1") is True  # 메시지는 지운다
    assert job_row(job).status == "finished"
    assert run("normal", 99999, "stage1") is True  # 없는 작업


def test_stage2_waits_for_input(me):
    _, job = add_video(me, status="stage1_done")
    assert run("zero_candidates", job, "stage2") is True
    assert job_row(job).status == "stage1_done"


def test_stage2_zero_candidates_ends_exhausted(me):
    _, job = add_video(me, status="stage1_done", input_done=True)
    assert run("zero_candidates", job, "stage2") is True
    assert job_row(job).status == "exhausted"


def test_stage2_failure_is_vlm_outage(me):
    _, job = add_video(me, status="stage1_done", input_done=True)
    run("stage2_fail_always", job, "stage2")
    row = job_row(job)
    assert (row.status, row.failure_kind) == ("failed", "vlm_outage")


def test_unbuilt_paths_keep_message(me):
    _, job = add_video(me, status="stage1_done", input_done=True)
    assert run("normal", job, "clip") is False


def queue_dir():
    path = STORAGE / "scratch" / "backend" / "queue"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_poll_moves_message_to_taken_and_deletes_when_done(me):
    _, job = add_video(me, status="queued")
    (queue_dir() / "1-a-stage1.json").write_text(json.dumps({"job_id": job, "kind": "stage1"}))
    worker = fake_worker.Worker("normal", step=False)
    assert worker.poll_once() is True
    assert job_row(job).status == "stage1_done"
    assert list(queue_dir().glob("*.json")) == []
    assert list((queue_dir() / "taken").glob("*.json")) == []
    assert worker.poll_once() is False


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "{}",
        '{"job_id": "7", "kind": "stage1"}',
        '{"job_id": 1, "kind": "rm -rf"}',
        "[1]",
    ],
)
def test_poll_skips_invalid_messages_and_keeps_them(me, content):
    (queue_dir() / "1-a-x.json").write_text(content)
    assert fake_worker.Worker("normal", step=False).poll_once() is True
    assert (queue_dir() / "taken" / "1-a-x.json").exists()


def test_scenario_must_be_in_allow_list():
    with pytest.raises(SystemExit):
        fake_worker.main(["--scenario", "../../etc/passwd"])


def test_refuses_to_start_outside_local_mode(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "app_mode", "aws", raising=False)
    with pytest.raises(SystemExit):
        fake_worker.main([])


def test_step_mode_stops_on_eof(me, monkeypatch):
    import io

    _, job = add_video(me, status="queued")
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    with pytest.raises(SystemExit):
        fake_worker.Worker("normal", step=True).handle(job, "stage1")
    assert job_row(job).status == "queued"
