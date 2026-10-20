"""로컬 가짜 워커 (D-159~D-161). 실행: uv run python -m local.fake_worker [--scenario 이름] [--step]

백엔드와 다른 프로세스로 띄운다. 큐 폴더의 메시지를 가져가 DB 상태를 04장 4.3 전이대로 바꾼다.
"""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from app.jobs import KINDS
from app.storage import storage_root

STEP_SECONDS = 2  # 상태를 바꾸는 UPDATE 사이의 대기 (D-160)
POLL_SECONDS = 1
STILL = Path(__file__).parent / "still.jpg"  # 합성 이미지 1920x1080. 팀장 fixtures가 오면 교체한다

# 허용 목록 (D-161 2번). 나머지 시나리오는 단계 4에서 후보·클립과 함께 더한다.
SCENARIOS = (
    "normal",
    "no_vehicles",
    "zero_candidates",
    "input_error",
    "stage1_fail_once",
    "stage1_fail_always",
    "stage2_fail_once",
    "stage2_fail_always",
)

# 정지 장면에서 탐지된 차량. 이미지 속 사각형 위치와 같다
DETECTIONS = [
    {"det_id": 1, "bbox": [810, 440, 960, 620], "conf": 0.91},
    {"det_id": 2, "bbox": [950, 435, 1120, 625], "conf": 0.88},
]
FAKE_VIDEO = {"d": 86400.0, "f": 30.0, "w": 1920, "h": 1080}  # 길이(초)·fps·가로·세로


class Worker:
    def __init__(self, scenario: str, step: bool):
        self.scenario = scenario
        self.step = step
        self.engine = get_engine()

    # ---- 진행 속도 (D-160) ----
    def pause(self, job_id: int, change: str) -> None:
        if not self.step:
            time.sleep(STEP_SECONDS)
            return
        print(f"[job {job_id}] {change}   (Enter로 진행)", flush=True)
        if sys.stdin.readline() == "":  # EOF면 진행하지 않고 끝낸다
            raise SystemExit("input closed; stopping without writing results")

    def log(self, job_id: int, message: str) -> None:
        print(f"[job {job_id}] {message}", flush=True)

    # ---- 전이 ----
    def job(self, job_id: int):
        with self.engine.connect() as conn:
            return conn.execute(
                text(
                    "SELECT id, video_id, status, user_retry_count, input_completed_at "
                    "FROM analysis_jobs WHERE id = :j"
                ),
                {"j": job_id},
            ).one_or_none()

    def move(self, job_id: int, frm: str, to: str, set_clause: str = "") -> bool:
        """조건부 UPDATE (04장 4.4). 이미 다른 상태면 0행이라 False."""
        with self.engine.begin() as conn:
            sql = f"UPDATE analysis_jobs SET status = :to, {set_clause}updated_at = now() WHERE id = :j AND status = :frm"  # noqa: S608
            return conn.execute(text(sql), {"j": job_id, "frm": frm, "to": to}).rowcount == 1

    def fail(self, job_id: int, running: str, kind: str, message: str) -> None:
        self.pause(job_id, f"{running} → failed ({kind})")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE analysis_jobs SET status = 'failed', failure_kind = :k, error_message = :m, "
                    "updated_at = now() WHERE id = :j AND status = :s"
                ),
                {"j": job_id, "k": kind, "m": message, "s": running},
            )

    def should_fail(self, name: str, retry_count: int) -> bool:
        if self.scenario == f"{name}_always":
            return True
        return self.scenario == f"{name}_once" and retry_count == 0  # D-161 3번

    # ---- 메시지 종류별 처리. True면 메시지를 지운다 ----
    def stage1(self, job_id: int) -> bool:
        row = self.job(job_id)
        if row is None:
            return True
        if row.status == "queued":
            self.pause(job_id, "queued → stills_running")
            if not self.move(job_id, "queued", "stills_running", "stage1_started_at = now(), "):
                return True
        elif row.status != "stills_running":
            return True  # 이미 처리했거나 맡는 상태가 아니다

        if self.scenario == "input_error":
            self.fail(job_id, "stills_running", "input_error", "fake worker: unreadable video")
            return True
        if self.should_fail("stage1_fail", row.user_retry_count):
            self.fail(job_id, "stills_running", "worker_died", "fake worker: injected failure")
            return True

        key = f"videos/{row.video_id}/stills/0.jpg"
        target = storage_root() / "masked" / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(STILL, target)
        detections = [] if self.scenario == "no_vehicles" else DETECTIONS

        self.pause(job_id, "stills_running → stage1_done")
        with self.engine.begin() as conn:
            moved = conn.execute(
                text(
                    "UPDATE analysis_jobs SET status = 'stage1_done', stage1_ended_at = now(), "
                    "updated_at = now() WHERE id = :j AND status = 'stills_running'"
                ),
                {"j": job_id},
            ).rowcount
            if moved == 1:
                conn.execute(
                    text(
                        "UPDATE videos SET duration_sec = :d, fps = :f, width = :w, height = :h WHERE id = :v"
                    ),
                    {"v": row.video_id, **FAKE_VIDEO},
                )
                conn.execute(
                    text(
                        "INSERT INTO still_frames (analysis_job_id, t_sec, masked_s3_key, detections) "
                        "VALUES (:j, 0.0, :k, CAST(:d AS jsonb)) ON CONFLICT (analysis_job_id) DO NOTHING"
                    ),
                    {"j": job_id, "k": key, "d": json.dumps(detections)},
                )
        return True

    def stage2(self, job_id: int) -> bool:
        row = self.job(job_id)
        if row is None:
            return True
        if row.status == "stage1_done":
            if row.input_completed_at is None:
                return True  # 입력 전에는 2단계를 시작하지 않는다
            self.pause(job_id, "stage1_done → stage2_running")
            if not self.move(
                job_id, "stage1_done", "stage2_running", "stage2_started_at = now(), "
            ):
                return True
        elif row.status != "stage2_running":
            return True

        if self.should_fail("stage2_fail", row.user_retry_count):
            self.fail(job_id, "stage2_running", "vlm_outage", "fake worker: injected failure")
            return True
        if self.scenario == "zero_candidates":
            self.pause(job_id, "stage2_running → exhausted")
            self.move(job_id, "stage2_running", "exhausted", "stage2_ended_at = now(), ")
            return True
        self.log(job_id, "this scenario needs candidates (not built yet); message stays in taken/")
        return False

    def handle(self, job_id: int, kind: str) -> bool:
        if kind == "stage1":
            return self.stage1(job_id)
        if kind == "stage2":
            return self.stage2(job_id)
        self.log(job_id, f"{kind} is not built yet; message stays in taken/")
        return False

    # ---- 큐 폴더 (D-159) ----
    @property
    def queue(self) -> Path:
        return storage_root() / "scratch" / "backend" / "queue"

    def poll_once(self) -> bool:
        """가장 오래된 메시지 하나를 가져가 처리한다. 메시지가 없으면 False."""
        files = sorted(p for p in self.queue.glob("*.json") if not p.name.startswith("."))
        if not files:
            return False
        taken = self.queue / "taken"
        taken.mkdir(exist_ok=True)
        mine = taken / files[0].name
        try:
            os.rename(files[0], mine)  # 옮기기에 성공한 쪽만 처리한다
        except FileNotFoundError:
            return True
        message = self.read(mine)
        if message is not None and self.handle(*message):
            mine.unlink(missing_ok=True)
        return True

    def run(self) -> None:
        self.queue.mkdir(parents=True, exist_ok=True)
        print(f"fake worker started (scenario={self.scenario}, step={self.step})", flush=True)
        while True:
            if not self.poll_once():
                time.sleep(POLL_SECONDS)

    @staticmethod
    def read(path: Path) -> tuple[int, str] | None:
        """손으로 넣은 파일도 있으므로 job_id는 정수, kind는 허용 목록인지 확인한다."""
        try:
            data = json.loads(path.read_text())
            job_id, kind = data["job_id"], data["kind"]
        except (OSError, ValueError, KeyError, TypeError):
            print(f"skipping {path.name}: unreadable message", flush=True)
            return None
        if type(job_id) is not int or kind not in KINDS:
            print(f"skipping {path.name}: invalid job_id or kind", flush=True)
            return None
        return job_id, kind


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="local fake worker")
    parser.add_argument("--scenario", default="normal", choices=SCENARIOS)
    parser.add_argument("--step", action="store_true", help="wait for Enter before each change")
    args = parser.parse_args(argv)
    if get_settings().app_mode != "local":  # D-159 5번
        raise SystemExit("fake worker runs only when APP_MODE=local")
    try:
        Worker(args.scenario, args.step).run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
