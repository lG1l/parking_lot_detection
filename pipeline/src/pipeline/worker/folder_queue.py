"""로컬 모드의 폴더 큐 (D-159, D-361 나-4). 메시지 하나가 JSON 파일 하나다.

큐 폴더: local_storage/scratch/backend/queue/<밀리초>-<job_id>-<kind>.json
받기는 파일을 queue/taken/으로 옮기는 것이고, 처리가 끝나면 그 파일을 지운다.
AWS 모드(SQS)는 10-라에서 이 파일과 같은 모양의 함수로 만든다.
"""

import json
import os
from pathlib import Path

# 메시지 종류 (04장 4.6). backend/app/jobs.py의 KINDS와 같다
KINDS = ("stage1", "stage2", "next_batch")

# 가져간 메시지를 두는 폴더 이름. 큐 폴더 아래에 있다
TAKEN_DIR = "taken"


def parse_message(content: str) -> tuple[int, str] | None:
    """메시지 내용에서 (작업 번호, 종류)를 꺼낸다. 형식이 틀리면 None이다.

    손으로 넣은 파일도 있으므로 job_id가 정수인지, kind가 허용 목록인지 본다.
    """
    try:
        data = json.loads(content)
        job_id, kind = data["job_id"], data["kind"]
    except (ValueError, KeyError, TypeError):
        return None
    # True·False도 int로 통하므로 isinstance가 아니라 type으로 본다
    if type(job_id) is not int or kind not in KINDS:
        return None
    return job_id, kind


def _read_message(path: Path) -> tuple[int, str] | None:
    """메시지 파일을 읽는다. 못 읽거나 형식이 틀리면 None이다."""
    try:
        return parse_message(path.read_text())
    except OSError:
        return None


def _move_to_taken(path: Path) -> Path | None:
    """메시지 파일을 taken/으로 옮긴다. 다른 쪽이 먼저 가져갔으면 None이다."""
    taken_dir = path.parent / TAKEN_DIR
    taken_dir.mkdir(exist_ok=True)
    taken_path = taken_dir / path.name
    try:
        os.rename(path, taken_path)  # 옮기기에 성공한 쪽만 처리한다
    except FileNotFoundError:
        return None
    return taken_path


def take_oldest(queue_dir: Path, kind: str) -> tuple[Path, int] | None:
    """종류가 kind인 가장 오래된 메시지를 가져가 (taken/의 파일, 작업 번호)를 준다. 없으면 None이다.

    다른 종류의 메시지는 건드리지 않고 큐에 둔다 (나-4).
    못 읽는 메시지는 한 줄을 찍고 taken/에 남긴다 (가짜 워커와 같다).
    """
    if not queue_dir.is_dir():
        return None
    # 파일 이름이 밀리초로 시작해 이름순이 오래된 순이다. "."으로 시작하는 파일은 쓰는 중인 파일이다
    paths = sorted(p for p in queue_dir.glob("*.json") if not p.name.startswith("."))
    for path in paths:
        message = _read_message(path)
        if message is None:
            if _move_to_taken(path) is not None:
                print(f"skipping {path.name}: unreadable message", flush=True)
            continue
        job_id, message_kind = message
        if message_kind != kind:
            continue
        taken_path = _move_to_taken(path)
        if taken_path is not None:
            return taken_path, job_id
    return None


def delete_message(taken_path: Path) -> None:
    """처리가 끝난 메시지를 지운다."""
    taken_path.unlink(missing_ok=True)
