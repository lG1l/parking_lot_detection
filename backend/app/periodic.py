"""백엔드 주기 작업. API 서버와 따로 하나만 띄운다: `python -m app.periodic` (D-105)."""

import logging
import time

import boto3
from sqlalchemy import text

from app import jobs
from app.config import get_settings
from app.db import get_engine
from app.videos import VIEW_DAYS

logger = logging.getLogger(__name__)

TICK_SECONDS = 5  # GPU 켜기 점검·재전송 주기 (D-42, D-56)
HOURLY_SECONDS = 3600  # 파기·동의 기록 정리 주기 (D-106)
AGREEMENT_DAYS = 90  # 동의 기록 보관 기간 (04장 upload_agreements)

# 대기 상태별로 다시 넣을 메시지 (04장 4.6 표, D-107)
REQUEUE_KIND = {"queued": "stage1", "stage1_done": "stage2", "batch_running": "next_batch"}


def mark_expired() -> None:
    """30일이 지난 영상에 파기 표시와 파기 기록을 한 트랜잭션으로 남긴다. S3는 보지 않는다 (D-142)."""
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "WITH due AS ("
                "  UPDATE videos SET raw_deleted_at = now(), masked_deleted_at = now()"
                "   WHERE raw_deleted_at IS NULL"
                "     AND upload_completed_at < now() - make_interval(days => :d)"
                "  RETURNING id) "
                "INSERT INTO access_logs (video_id, action) "
                "SELECT id, 'delete_raw' FROM due UNION ALL SELECT id, 'delete_masked' FROM due"
            ),
            {"d": VIEW_DAYS},
        )


def delete_old_agreements() -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "DELETE FROM upload_agreements WHERE agreed_at < now() - make_interval(days => :d)"
            ),
            {"d": AGREEMENT_DAYS},
        )


def requeue_stalled() -> None:
    """대기 상태로 기준 시간 넘게 멈춘 작업을 다시 넣는다. 상태는 바꾸지 않는다 (D-56, D-153)."""
    minutes = get_settings().requeue_after_minutes
    with get_engine().connect() as conn:
        stalled = conn.execute(
            text(
                "SELECT id, status FROM analysis_jobs "
                "WHERE (status IN ('queued', 'batch_running') "
                "       OR (status = 'stage1_done' AND input_completed_at IS NOT NULL)) "
                "  AND updated_at < now() - make_interval(mins => :m)"
            ),
            {"m": minutes},
        ).all()
    for job in stalled:
        # 그사이 워커가 상태를 바꿨으면 0행이라 넣지 않는다. 넣기에 실패하면 되돌려 다음 점검에 다시 한다
        with get_engine().begin() as conn:
            touched = conn.execute(
                text(
                    "UPDATE analysis_jobs SET updated_at = now() "
                    "WHERE id = :j AND status = :s AND updated_at < now() - make_interval(mins => :m)"
                ),
                {"j": job.id, "s": job.status, "m": minutes},
            ).rowcount
            if touched:
                jobs.send_job(job.id, REQUEUE_KIND[job.status])


def _waiting_for_gpu() -> bool:
    with get_engine().connect() as conn:
        return conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM analysis_jobs "
                "WHERE status IN ('queued', 'stills_running', 'stage2_running', 'batch_running') "
                "   OR (status = 'stage1_done' AND input_completed_at IS NOT NULL))"
            )
        ).scalar_one()


class GpuCheck:
    """작업은 있는데 GPU가 꺼져 있으면 켠다. 같은 에러가 이어지면 로그를 접는다 (D-42)."""

    def __init__(self) -> None:
        self.last_error: str | None = None
        self.failures = 0

    def tick(self) -> None:
        settings = get_settings()
        if settings.app_mode == "local" or not _waiting_for_gpu():  # 로컬에서는 끈다
            return
        try:
            ec2 = boto3.client("ec2", region_name=settings.aws_region)
            found = ec2.describe_instances(InstanceIds=[settings.gpu_instance_id])
            state = found["Reservations"][0]["Instances"][0]["State"]["Name"]
            if state != "stopped":  # pending·running·stopping은 다음 점검에서 다시 본다
                return
            ec2.start_instances(InstanceIds=[settings.gpu_instance_id])
        except Exception as exc:  # noqa: BLE001 - 다음 점검에서 다시 한다
            code = getattr(exc, "response", {}).get("Error", {}).get("Code") or type(exc).__name__
            self.failures += 1
            if code != self.last_error:
                logger.warning(
                    "GPU start failed: %s (same error suppressed until it changes)", code
                )
                self.last_error = code
            return
        if self.failures:
            logger.info("GPU start succeeded after %d failures", self.failures)
        else:
            logger.info("GPU start requested")
        self.last_error, self.failures = None, 0


def _safely(task) -> None:
    try:
        task()
    except Exception:
        logger.exception("periodic task %s failed", task.__name__)  # 다음 회차에 다시 한다


def run() -> None:
    gpu = GpuCheck()
    last_hourly = None
    while True:
        now = time.monotonic()
        if (
            last_hourly is None or now - last_hourly >= HOURLY_SECONDS
        ):  # 켤 때 한 번, 그 뒤 1시간마다
            last_hourly = now
            _safely(mark_expired)
            _safely(delete_old_agreements)
        _safely(requeue_stalled)
        _safely(gpu.tick)
        time.sleep(TICK_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
