"""pipeline 워커의 진입점 (10-나, D-361). 로컬 모드의 폴더 큐에서 stage1 메시지를 받아 정지 장면 작업을 한다.

실행 (pipeline/ 폴더에서. APP_MODE·DATABASE_URL은 backend/.env와 같은 값이다. Ctrl+C로 끝낸다):
    uv run python -m pipeline.worker.main <YOLO 가중치> <비식별화 모델 폴더>

쓰는 자리와 순서는 backend의 가짜 워커(backend/local/fake_worker.py)와 같다.
이 워커와 가짜 워커는 같은 큐를 보므로 함께 켜지 않는다.
stage2·next_batch 메시지는 건드리지 않고 큐에 둔다 (나-4. 10-다에서 만든다).
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path

import cv2
from sqlalchemy import Engine

from pipeline.chain import CHAIN_ERRORS, DIR_STILL, run_still_job
from pipeline.worker import db, folder_queue

# 큐에 메시지가 없을 때 다시 보기까지 쉬는 시간 (초). 가짜 워커와 같다
POLL_SECONDS = 1

# 정지 장면 작업이 작업 폴더의 1_still/ 아래에 쓰는 파일 이름 (still.py)
DETECTIONS_NAME = "detections.json"
MASKED_STILL_NAME = "0.jpg"


class VideoInfoError(Exception):
    """영상의 폭·높이·fps·프레임 수를 읽지 못했을 때."""


# 알려진 오류. 이 밖의 예외는 버그라 잡지 않는다 (나-7)
WORKER_ERRORS = (*CHAIN_ERRORS, VideoInfoError)


# ---- 키·경로 (04장 4.9, D-361 "읽고 쓰는 자리") ----
def storage_root() -> Path:
    """local_storage 폴더. LOCAL_STORAGE_DIR이 비면 저장소 루트의 local_storage/다 (backend와 같다)."""
    configured = os.environ.get("LOCAL_STORAGE_DIR")
    if configured:
        return Path(configured)
    # 이 파일은 <저장소 루트>/pipeline/src/pipeline/worker/main.py다
    return Path(__file__).resolve().parents[4] / "local_storage"


def queue_dir(storage: Path) -> Path:
    """backend가 메시지를 넣는 큐 폴더."""
    return storage / "scratch" / "backend" / "queue"


def raw_video_path(storage: Path, s3_key: str) -> Path:
    """원본 영상의 자리. s3_key는 videos.s3_key다."""
    return storage / "raw" / s3_key


def masked_still_key(video_id: int) -> str:
    """가린 정지 장면의 키 (still_frames.masked_s3_key)."""
    return f"videos/{video_id}/stills/0.jpg"


def masked_path(storage: Path, key: str) -> Path:
    """마스킹본 키의 자리. 화면이 보는 파일이다."""
    return storage / "masked" / key


def job_dir(storage: Path, job_id: int) -> Path:
    """작업 폴더. 가리기 전 화면(0_check.jpg)이 있어 masked/ 밖에 둔다 (나-9)."""
    return storage / "scratch" / "pipeline" / "worker" / "jobs" / str(job_id)


# ---- 1단계 ----
def read_video_info(video_path: str) -> dict:
    """영상의 길이(초)·fps·폭·높이를 OpenCV로 읽는다. 길이 = 프레임 수 ÷ fps (나-6)."""
    capture = cv2.VideoCapture(video_path)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = capture.get(cv2.CAP_PROP_FPS)
    frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    capture.release()
    if width <= 0 or height <= 0 or fps <= 0 or frame_count <= 0:
        raise VideoInfoError(f"영상 정보를 읽지 못했습니다: {video_path}")
    return {"duration_sec": frame_count / fps, "fps": fps, "width": width, "height": height}


def run_stage1(
    engine: Engine, storage: Path, job_id: int, job, weights_path: str, model_dir: str
) -> None:
    """정지 장면을 만들고, 가린 화면을 masked/에 둔 뒤에 DB에 결과를 쓴다 (나-5).

    파일이 먼저여야 상태가 stage1_done일 때 화면이 볼 파일이 있다.
    """
    video_path = str(raw_video_path(storage, job.s3_key))
    out_dir = job_dir(storage, job_id)
    run_still_job(video_path, weights_path, model_dir, str(out_dir))
    video_info = read_video_info(video_path)
    detections = json.loads((out_dir / DIR_STILL / DETECTIONS_NAME).read_text())

    key = masked_still_key(job.video_id)
    target = masked_path(storage, key)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(out_dir / DIR_STILL / MASKED_STILL_NAME, target)

    if db.write_stage1_result(engine, job_id, job.video_id, video_info, key, detections):
        print(f"job {job_id}: 1단계 끝 (차량 {len(detections)}대)", flush=True)
    else:
        print(f"job {job_id}: 상태가 stills_running이 아니라 결과를 쓰지 않았습니다", flush=True)


def handle_stage1(
    engine: Engine, storage: Path, job_id: int, weights_path: str, model_dir: str
) -> bool:
    """stage1 메시지 하나를 처리한다. True면 메시지를 지우고, False면 taken/에 남긴다."""
    job = db.read_job(engine, job_id)
    if job is None:
        return True
    if job.status == "queued":
        if not db.start_stage1(engine, job_id):
            return True  # 다른 쪽이 먼저 바꿨다
    elif job.status != "stills_running":
        return True  # 이미 처리했거나 맡는 상태가 아니다
    # stills_running으로 받았으면 앞선 처리가 죽은 것이라 처음부터 다시 한다 (06장 6.2)

    print(f"job {job_id}: 1단계 시작", flush=True)
    try:
        run_stage1(engine, storage, job_id, job, weights_path, model_dir)
    except WORKER_ERRORS as e:
        # 실패를 가르지 않는다 (임시, 나-7). 상태는 stills_running 그대로 두고 메시지를 남긴다
        print(f"오류: job {job_id}: {e}", flush=True)
        return False
    return True


# ---- 고리 ----
def poll_once(engine: Engine, storage: Path, weights_path: str, model_dir: str) -> bool:
    """가장 오래된 stage1 메시지 하나를 처리한다. 메시지가 없으면 False다."""
    taken = folder_queue.take_oldest(queue_dir(storage), "stage1")
    if taken is None:
        return False
    taken_path, job_id = taken
    if handle_stage1(engine, storage, job_id, weights_path, model_dir):
        folder_queue.delete_message(taken_path)
    return True


def main(args: list[str]) -> int:
    """명령 인자 2개를 받아 큐를 계속 본다. 종료 코드를 준다."""
    if len(args) != 2:
        print("사용법: python -m pipeline.worker.main <YOLO 가중치> <비식별화 모델 폴더>")
        return 2
    if os.environ.get("APP_MODE") != "local":
        # aws 모드(SQS·S3)는 10-라에서 만든다 (나-3)
        print("APP_MODE=local일 때만 돕니다")
        return 1
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL이 없습니다")
        return 1
    weights_path, model_dir = args
    engine = db.make_engine(database_url)
    storage = storage_root()
    print(f"워커 시작 (큐: {queue_dir(storage)})", flush=True)
    try:
        while True:
            if not poll_once(engine, storage, weights_path, model_dir):
                time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
