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

# 허용 목록 (D-161 2번)
SCENARIOS = (
    "normal",
    "many",
    "no_vehicles",
    "zero_candidates",
    "clip_fail_retry_ok",
    "clip_fail_final",
    "clip_fail_all",
    "input_error",
    "stage1_fail_once",
    "stage1_fail_always",
    "stage2_fail_once",
    "stage2_fail_always",
    "batch_fail_once",
    "batch_fail_always",
)
# 다음 묶음이 있어야 [다음]이 next_batch를 넣으므로 batch_fail도 many의 후보 수를 쓴다
MANY = ("many", "batch_fail_once", "batch_fail_always")
CLIP_TRIES = 3  # 최초 포함 (D-109)

# 정지 장면에서 탐지된 차량. 이미지 속 사각형 위치와 같다
DETECTIONS = [
    {"det_id": 1, "bbox": [810, 440, 960, 620], "conf": 0.91},
    {"det_id": 2, "bbox": [950, 435, 1120, 625], "conf": 0.88},
]
# ffmpeg가 없는 환경에서도 돌도록 클립 파일은 자리표시 바이트다. API·상태 흐름만 확인하며 재생은 안 된다.
FAKE_CLIP = b"fake mp4 clip for local api checks"
CROP_BBOX = [800, 430, 1130, 630]
BATCH_SIZE = 10  # 01장 1.6
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
        self.pause(job_id, "stage2_running → ready")
        self.make_candidates(job_id)
        self.make_pending_clips(job_id)
        self.move(
            job_id,
            "stage2_running",
            "ready",
            "stage2_ended_at = now(), current_batch_no = 1, current_failed_batch_no = ("
            "SELECT 1 FROM candidates WHERE analysis_job_id = :j AND list_kind = 'parse_failed' "
            "LIMIT 1), ",
        )
        return True

    # ---- 후보·클립 (04장 4.4) ----
    def make_candidates(self, job_id: int) -> None:
        """후보를 만들고 목록마다 점수순 rank를 매긴다. 묶음 1·2에 번호를 매겨 클립 행을 만든다."""
        main_count, failed_count = (25, 3) if self.scenario in MANY else (3, 0)
        with self.engine.begin() as conn:
            if conn.execute(
                text("SELECT 1 FROM candidates WHERE analysis_job_id = :j LIMIT 1"), {"j": job_id}
            ).first():
                return  # 재전달된 메시지가 후보를 두 번 만들지 않는다
            for i in range(main_count + failed_count):
                failed = i >= main_count
                conn.execute(
                    text(
                        "INSERT INTO candidates (analysis_job_id, judged_at_sec, channel, rule_name, "
                        "track_id, vlm_pass1, vlm_score, list_kind, rank) "
                        "VALUES (:j, :t, 'A', 'fake_rule', :tr, :p1, :sc, :lk, :rk)"
                    ),
                    {
                        "j": job_id,
                        "t": 600.0 + i * 120,
                        "tr": i + 1,
                        "p1": None if failed else True,
                        "sc": None if failed else 95 - i,
                        "lk": "parse_failed" if failed else "main",
                        "rk": i - main_count + 1 if failed else i + 1,
                    },
                )
            self.number_batches(conn, job_id, ("main", "parse_failed"), upto=2)

    def number_batches(
        self, conn, job_id: int, kinds: tuple[str, ...], upto: int | None = None
    ) -> bool:
        """번호 없는 후보 10개에 다음 batch_no를 매기고 pending 클립 행을 만든다. 목록마다 따로 센다.

        upto가 있으면 그 번호까지, 없으면 목록마다 한 묶음만 만든다. 하나라도 만들었으면 True.
        """
        made = False
        for kind in kinds:
            while True:
                top = conn.execute(
                    text(
                        "SELECT coalesce(max(batch_no), 0) FROM candidates "
                        "WHERE analysis_job_id = :j AND list_kind = :k"
                    ),
                    {"j": job_id, "k": kind},
                ).scalar_one()
                if upto is not None and top >= upto:
                    break
                ids = conn.execute(
                    text(
                        "SELECT id, judged_at_sec FROM candidates WHERE analysis_job_id = :j "
                        "AND list_kind = :k AND batch_no IS NULL ORDER BY rank LIMIT :n"
                    ),
                    {"j": job_id, "k": kind, "n": BATCH_SIZE},
                ).all()
                if not ids:
                    break
                made = True
                for row in ids:
                    conn.execute(
                        text("UPDATE candidates SET batch_no = :b WHERE id = :c"),
                        {"b": top + 1, "c": row.id},
                    )
                    conn.execute(
                        text(
                            "INSERT INTO candidate_clips (candidate_id, start_sec, end_sec, crop_bbox) "
                            "VALUES (:c, :s, :e, :box)"
                        ),
                        {
                            "c": row.id,
                            "s": row.judged_at_sec - 15,
                            "e": row.judged_at_sec + 15,
                            "box": CROP_BBOX,
                        },
                    )
                if upto is None:
                    break
        return made

    def clip_failures(self, list_kind: str, rank: int) -> int:
        """이 후보의 클립이 처음부터 몇 번 실패할지 (D-161 5번 표)."""
        if self.scenario == "clip_fail_all":
            return CLIP_TRIES
        if list_kind != "main":
            return 0
        if self.scenario == "clip_fail_retry_ok":
            return {1: 1, 2: 2}.get(rank, 0)  # 1위는 2번째, 2위는 3번째 시도에 성공
        if self.scenario == "clip_fail_final":
            return CLIP_TRIES if rank == 2 else 0
        return 0

    def fail_clip(self, clip_id: int, candidate_id: int, tries: int) -> None:
        """running 클립을 failed로 바꾼다. 3번째면 후보를 unavailable로, 아니면 새 pending 행을 만든다 (04장 candidate_clips)."""
        with self.engine.begin() as conn:
            moved = conn.execute(
                text(
                    "UPDATE candidate_clips SET status = 'failed' WHERE id = :c AND status = 'running'"
                ),
                {"c": clip_id},
            ).rowcount
            if moved != 1:
                return
            if tries < CLIP_TRIES:
                conn.execute(
                    text(
                        "INSERT INTO candidate_clips (candidate_id, start_sec, end_sec, crop_bbox) "
                        "SELECT candidate_id, start_sec, end_sec, crop_bbox FROM candidate_clips "
                        "WHERE id = :c"
                    ),
                    {"c": clip_id},
                )
            else:
                conn.execute(
                    text(
                        "UPDATE candidates SET verdict = 'unavailable' WHERE id = :d AND verdict = 'unseen'"
                    ),
                    {"d": candidate_id},
                )

    def make_pending_clips(self, job_id: int) -> None:
        """pending 클립을 하나씩 가져가(pending → running) 파일을 쓰고 done으로 바꾼다."""
        while True:
            with self.engine.begin() as conn:
                clip = conn.execute(
                    text(
                        "UPDATE candidate_clips SET status = 'running' WHERE id = ("
                        "SELECT c.id FROM candidate_clips c JOIN candidates d ON d.id = c.candidate_id "
                        "WHERE d.analysis_job_id = :j AND c.status = 'pending' "
                        "ORDER BY c.id LIMIT 1 FOR UPDATE SKIP LOCKED) AND status = 'pending' "
                        "RETURNING id, candidate_id"
                    ),
                    {"j": job_id},
                ).one_or_none()
                if clip is not None:
                    info = conn.execute(
                        text(
                            "SELECT d.list_kind, d.rank, count(c.id) AS tries FROM candidates d "
                            "JOIN candidate_clips c ON c.candidate_id = d.id WHERE d.id = :d "
                            "GROUP BY d.id"
                        ),
                        {"d": clip.candidate_id},
                    ).one()
            if clip is None:
                return
            if info.tries <= self.clip_failures(info.list_kind, info.rank):
                self.fail_clip(clip.id, clip.candidate_id, info.tries)
                continue
            video_id = self.job(job_id).video_id
            key = f"videos/{video_id}/clips/{clip.id}.mp4"
            target = storage_root() / "masked" / key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(FAKE_CLIP)
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE candidate_clips SET status = 'done', masked_s3_key = :k "
                        "WHERE id = :c AND status = 'running'"
                    ),
                    {"k": key, "c": clip.id},
                )

    def next_batch(self, job_id: int) -> bool:
        """미리 만들던 pending 클립부터 마치고, 앞서 있지 않은 목록에 한 묶음을 더 만든다 (04장 4.4)."""
        row = self.job(job_id)
        if row is None:
            return True
        if row.status in ("ready", "batch_running") and self.should_fail(
            "batch_fail", row.user_retry_count
        ):
            self.fail(job_id, row.status, "worker_died", "fake worker: injected failure")
            return True
        self.make_pending_clips(job_id)
        with self.engine.begin() as conn:
            job = conn.execute(
                text(
                    "SELECT status, current_batch_no, current_failed_batch_no "
                    "FROM analysis_jobs WHERE id = :j FOR UPDATE"
                ),
                {"j": job_id},
            ).one()
            if job.status not in ("ready", "batch_running"):
                return True
            current = {"main": job.current_batch_no, "parse_failed": job.current_failed_batch_no}
            made = False
            for kind, cur in current.items():
                if cur is None:
                    continue
                top = conn.execute(
                    text(
                        "SELECT coalesce(max(batch_no), 0) FROM candidates "
                        "WHERE analysis_job_id = :j AND list_kind = :k"
                    ),
                    {"j": job_id, "k": kind},
                ).scalar_one()
                if top >= cur + 1:
                    continue  # 이미 한 묶음 앞서 있다
                made |= self.number_batches(conn, job_id, (kind,))
        if not made:
            self.finish_batch(job_id)
            return True
        self.pause(job_id, "batch_running → ready")
        self.make_pending_clips(job_id)
        self.finish_batch(job_id)
        return True

    def finish_batch(self, job_id: int) -> None:
        """전이 11: 두 목록의 지금 묶음 클립이 모두 만들어졌으면 batch_running → ready."""
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE analysis_jobs j SET status = 'ready', updated_at = now() "
                    "WHERE j.id = :j AND j.status = 'batch_running' AND NOT EXISTS ("
                    "SELECT 1 FROM candidate_clips c JOIN candidates d ON d.id = c.candidate_id "
                    "WHERE d.analysis_job_id = j.id AND c.status IN ('pending', 'running') "
                    "AND d.batch_no = CASE d.list_kind WHEN 'main' THEN j.current_batch_no "
                    "ELSE j.current_failed_batch_no END)"
                ),
                {"j": job_id},
            )

    def handle(self, job_id: int, kind: str) -> bool:
        if kind == "stage1":
            return self.stage1(job_id)
        if kind == "stage2":
            return self.stage2(job_id)
        if kind == "next_batch":
            return self.next_batch(job_id)
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
