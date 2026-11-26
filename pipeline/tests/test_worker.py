"""pipeline 워커(10-나, D-361)의 폴더 큐와 상태별 분기. 영상·모델·DB 없이 돈다."""

import pytest

from pipeline.worker import folder_queue


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
