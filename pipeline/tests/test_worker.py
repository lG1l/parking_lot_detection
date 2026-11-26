"""pipeline 워커(10-나, D-361)의 폴더 큐와 상태별 분기. 영상·모델·DB 없이 돈다."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.still import StillError
from pipeline.worker import folder_queue, main


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"job_id": 42, "kind": "stage1"}', (42, "stage1")),
        ('{"job_id": 42, "kind"', None),  # 깨진 JSON
        ('{"job_id": "42", "kind": "stage1"}', None),  # 작업 번호가 글자
        ('{"job_id": 42, "kind": "stage9"}', None),  # 없는 종류
    ],
)
def test_parse_message(content, expected):
    assert folder_queue.parse_message(content) == expected


def _put(queue_dir, name, job_id, kind):
    (queue_dir / name).write_text(f'{{"job_id": {job_id}, "kind": "{kind}"}}')


def test_take_oldest_takes_only_stage1(tmp_path):
    _put(tmp_path, "1-7-stage2.json", 7, "stage2")
    _put(tmp_path, "2-8-stage1.json", 8, "stage1")
    _put(tmp_path, "3-9-stage1.json", 9, "stage1")
    _put(tmp_path, ".tmp.json", 5, "stage1")

    taken_path, job_id = folder_queue.take_oldest(tmp_path, "stage1")

    assert job_id == 8
    assert taken_path == tmp_path / "taken" / "2-8-stage1.json"
    assert taken_path.is_file()
    # 나머지 셋은 큐에 그대로다
    left = sorted(p.name for p in tmp_path.iterdir() if p.is_file())
    assert left == [".tmp.json", "1-7-stage2.json", "3-9-stage1.json"]


def test_take_oldest_empty_broken_and_delete(tmp_path):
    # 빈 큐
    assert folder_queue.take_oldest(tmp_path, "stage1") is None

    # 깨진 JSON 파일은 taken/에 남고 가져간 것은 없다
    (tmp_path / "1-7-stage1.json").write_text("{broken")
    assert folder_queue.take_oldest(tmp_path, "stage1") is None
    assert (tmp_path / "taken" / "1-7-stage1.json").is_file()
    assert not (tmp_path / "1-7-stage1.json").exists()

    # 가져간 메시지 지우기
    _put(tmp_path, "2-8-stage1.json", 8, "stage1")
    taken_path, _ = folder_queue.take_oldest(tmp_path, "stage1")
    folder_queue.delete_message(taken_path)
    assert not taken_path.exists()


def test_keys_and_paths():
    storage = Path("/x")
    assert main.raw_video_path(storage, "videos/7/original.mp4") == Path(
        "/x/raw/videos/7/original.mp4"
    )
    key = main.masked_still_key(7)
    assert key == "videos/7/stills/0.jpg"
    assert main.masked_path(storage, key) == Path("/x/masked/videos/7/stills/0.jpg")
    assert main.job_dir(storage, 42) == Path("/x/scratch/pipeline/worker/jobs/42")


# (작업 상태, 정지 장면이 오류를 내는지, 정지 장면을 부른 횟수, 결과 쓰기 횟수, 메시지가 지워지는지)
@pytest.mark.parametrize(
    ("status", "still_fails", "still_calls", "result_writes", "deleted"),
    [
        (None, False, 0, 0, True),  # 작업 행 없음
        ("queued", False, 1, 1, True),
        ("stills_running", False, 1, 1, True),
        ("stage1_done", False, 0, 0, True),
        ("queued", True, 1, 0, False),  # 알려진 오류: 메시지를 taken/에 남긴다
    ],
)
def test_poll_once_by_status(
    tmp_path, monkeypatch, status, still_fails, still_calls, result_writes, deleted
):
    calls = {"still": 0, "write": 0}

    def fake_read_job(engine, job_id):
        if status is None:
            return None
        return SimpleNamespace(status=status, video_id=7, s3_key="videos/7/original.mp4")

    def fake_still_job(video_path, weights_path, model_dir, out_dir):
        calls["still"] += 1
        if still_fails:
            raise StillError("가짜 오류")
        still_dir = Path(out_dir) / main.DIR_STILL
        still_dir.mkdir(parents=True)
        (still_dir / main.DETECTIONS_NAME).write_text(json.dumps([{"det_id": 1}]))
        (still_dir / main.MASKED_STILL_NAME).write_bytes(b"jpg")

    def fake_write(engine, job_id, video_id, video_info, masked_key, detections):
        calls["write"] += 1
        return True

    monkeypatch.setattr(main.db, "read_job", fake_read_job)
    monkeypatch.setattr(main.db, "start_stage1", lambda engine, job_id: True)
    monkeypatch.setattr(main.db, "write_stage1_result", fake_write)
    monkeypatch.setattr(main, "run_still_job", fake_still_job)
    monkeypatch.setattr(main, "read_video_info", lambda video_path: {})

    queue = main.queue_dir(tmp_path)
    queue.mkdir(parents=True)
    _put(queue, "1-42-stage1.json", 42, "stage1")

    assert main.poll_once(None, tmp_path, "w.pt", "models") is True

    assert calls == {"still": still_calls, "write": result_writes}
    assert (queue / "taken" / "1-42-stage1.json").exists() is not deleted
    assert not (queue / "1-42-stage1.json").exists()
    if result_writes:
        assert main.masked_path(tmp_path, main.masked_still_key(7)).read_bytes() == b"jpg"
