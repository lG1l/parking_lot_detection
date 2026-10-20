from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app import jobs
from app.auth import current_user
from app.batches import _BUILDING
from app.db import get_engine
from app.errors import ApiError
from app.videos import MAX_USER_RETRIES, _error_kind, _owned_video, _view_expires_at

router = APIRouter(prefix="/api/videos")

_JOB = (
    "SELECT id, status, stage1_ended_at, stage2_ended_at, current_batch_no, "
    "current_failed_batch_no FROM analysis_jobs WHERE video_id = :v FOR UPDATE"
)


def _resume_point(conn, job) -> tuple[str, str]:
    """04장 4.3 "재시도로 되돌릴 상태" 표. (되돌릴 상태, 넣을 메시지)"""
    if job.stage1_ended_at is None:
        return "queued", "stage1"
    if job.stage2_ended_at is None:
        return "stage1_done", "stage2"
    for kind, current in (
        ("main", job.current_batch_no),
        ("parse_failed", job.current_failed_batch_no),
    ):
        if (
            current is not None
            and conn.execute(text(_BUILDING), {"j": job.id, "k": kind, "n": current}).scalar_one()
        ):
            return "batch_running", "next_batch"
    return "ready", "next_batch"


@router.post("/{video_id}/retry", status_code=202)
def retry(video_id: int, user: Annotated[dict, Depends(current_user)]):
    with get_engine().begin() as conn:
        _owned_video(conn, video_id, user["id"])
        job = conn.execute(text(_JOB), {"v": video_id}).one_or_none()
        if job is None or job.status != "failed":
            raise ApiError(409, "INVALID_STATE", "analysis has not failed")
        # 잠근 뒤 다시 읽어 실패 종류와 재시도 횟수를 최신으로 본다
        row = _owned_video(conn, video_id, user["id"])
        kind, _ = _error_kind(row, _view_expires_at(row.upload_completed_at))
        if kind == "expired":
            raise ApiError(409, "RAW_EXPIRED", "raw video was deleted or the viewing period ended")
        if kind == "file":
            raise ApiError(409, "RETRY_NOT_ALLOWED", "retrying will not change the result")
        if row.user_retry_count >= MAX_USER_RETRIES:
            raise ApiError(409, "RETRY_LIMIT_REACHED", "retry limit reached")
        next_status, message = _resume_point(conn, job)
        conn.execute(
            text(
                "UPDATE analysis_jobs SET status = :s, user_retry_count = user_retry_count + 1, "
                "failure_kind = NULL, error_message = NULL, updated_at = now() "
                "WHERE id = :j AND status = 'failed' AND user_retry_count < :max"
            ),
            {"s": next_status, "j": job.id, "max": MAX_USER_RETRIES},
        )
        jobs.send_job(job.id, message)  # 실패하면 예외로 롤백한다 (500)
    jobs.start_gpu()
    return {"status": next_status, "retry_left": MAX_USER_RETRIES - row.user_retry_count - 1}
