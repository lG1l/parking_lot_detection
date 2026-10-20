from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app import storage
from app.auth import current_user
from app.db import get_engine
from app.errors import ApiError
from app.uploads import _iso

router = APIRouter(prefix="/api/videos")

VIEW_DAYS = 30  # 열람기한: 업로드 완료 + 30일 (D-92)
MAX_USER_RETRIES = 3  # D-112

# 05장 5.5의 status 계산. 작업 행이 없으면 URL 발급(created_at)으로부터 30분을 본다 (D-47)
_STATUS = """
CASE WHEN j.status IS NOT NULL                                  THEN j.status
     WHEN v.created_at > now() - interval '30 minutes'          THEN 'uploading'
     ELSE 'upload_failed'
END
"""

_VIDEO = f"""
SELECT v.id, v.original_filename, v.created_at, v.upload_completed_at, v.duration_sec,
       v.raw_deleted_at, v.masked_deleted_at, now() AS now,
       j.id AS job_id, j.failure_kind, j.user_retry_count, j.input_completed_at,
       {_STATUS} AS status
  FROM videos v LEFT JOIN analysis_jobs j ON j.video_id = v.id
"""  # noqa: S608 - 상수만 이어 붙인다

# 04장 4.5: 나보다 먼저 줄에 섰고 아직 GPU 차례가 끝나지 않은 작업 수
_QUEUE_AHEAD = """
WITH q AS (
  SELECT id,
         CASE WHEN status IN ('queued', 'stills_running') THEN created_at
              ELSE input_completed_at END AS lined_up_at
    FROM analysis_jobs
   WHERE status IN ('queued', 'stills_running', 'stage2_running')
      OR (status = 'stage1_done' AND input_completed_at IS NOT NULL)
)
SELECT count(*) FROM q
 WHERE lined_up_at < (SELECT lined_up_at FROM q WHERE id = :job_id)
"""


def _view_expires_at(completed_at: datetime | None) -> datetime | None:
    return completed_at + timedelta(days=VIEW_DAYS) if completed_at else None


def _owned_video(conn, video_id: int, user_id: int):
    row = conn.execute(
        text(_VIDEO + " WHERE v.id = :v AND v.owner_user_id = :u"),
        {"v": video_id, "u": user_id},
    ).one_or_none()
    if row is None:
        raise ApiError(404, "VIDEO_NOT_FOUND", "video not found")
    return row


def _error_kind(row, expires_at: datetime | None) -> tuple[str, bool]:
    """9번 표의 위에서부터 처음 맞는 것. (error_kind, can_retry)"""
    retry_left = MAX_USER_RETRIES - row.user_retry_count
    if row.failure_kind == "input_error":
        return "file", False
    if row.raw_deleted_at is not None or (expires_at is not None and row.now > expires_at):
        return "expired", False
    if row.failure_kind == "vlm_outage":
        return "temporary", retry_left > 0
    return "service", retry_left > 0  # vlm_parse_rate·worker_died. 🚧 팀장 확인(05장 9번)


@router.get("")
def list_videos(user: Annotated[dict, Depends(current_user)]):
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(_VIDEO + " WHERE v.owner_user_id = :u ORDER BY v.created_at DESC, v.id DESC"),
            {"u": user["id"]},
        ).all()
    result = []
    for row in rows:
        expires_at = _view_expires_at(row.upload_completed_at)
        result.append(
            {
                "video_id": row.id,
                "original_filename": row.original_filename,
                "status": row.status,
                "created_at": _iso(row.created_at),
                "view_expires_at": _iso(expires_at) if expires_at else None,
            }
        )
    return result


@router.get("/{video_id}")
def get_video(video_id: int, user: Annotated[dict, Depends(current_user)]):
    with get_engine().connect() as conn:
        row = _owned_video(conn, video_id, user["id"])
        expires_at = _view_expires_at(row.upload_completed_at)
        input_done = row.input_completed_at is not None
        body = {
            "video_id": row.id,
            "original_filename": row.original_filename,
            "status": row.status,
            "input_done": input_done,
            "raw_deleted": row.raw_deleted_at is not None,
            "masked_deleted": row.masked_deleted_at is not None,
            "created_at": _iso(row.created_at),
            "duration_sec": row.duration_sec,
            "view_expires_at": _iso(expires_at) if expires_at else None,
        }
        if row.status == "queued" or (row.status == "stage1_done" and input_done):
            body["queue_ahead"] = conn.execute(
                text(_QUEUE_AHEAD), {"job_id": row.job_id}
            ).scalar_one()
        if row.status == "exhausted":
            total, unavailable = conn.execute(
                text(
                    "SELECT count(*), count(*) FILTER (WHERE verdict = 'unavailable') "
                    "FROM candidates WHERE analysis_job_id = :j"
                ),
                {"j": row.job_id},
            ).one()
            body["candidate_total"] = total
            body["candidate_unavailable"] = unavailable
        if row.status == "failed":
            kind, can_retry = _error_kind(row, expires_at)
            body["error_kind"] = kind
            body["can_retry"] = can_retry
            body["retry_left"] = MAX_USER_RETRIES - row.user_retry_count
    return body


@router.get("/{video_id}/still")
def get_still(video_id: int, user: Annotated[dict, Depends(current_user)]):
    with get_engine().connect() as conn:
        row = _owned_video(conn, video_id, user["id"])
        expires_at = _view_expires_at(row.upload_completed_at)
        # 만료를 먼저 본다. 파기된 키에 서명해 주면 브라우저가 S3의 404를 받는다
        if row.masked_deleted_at is not None or (expires_at is not None and row.now > expires_at):
            when = row.masked_deleted_at or expires_at
            raise ApiError(409, "MASKED_EXPIRED", f"masked files were deleted at {_iso(when)}")
        still = conn.execute(
            text(
                "SELECT s.id, s.t_sec, s.masked_s3_key, s.detections FROM still_frames s "
                "JOIN analysis_jobs j ON j.id = s.analysis_job_id WHERE j.video_id = :v"
            ),
            {"v": video_id},
        ).one_or_none()
    if still is None:
        raise ApiError(409, "INVALID_STATE", f"still frame is not ready (status: {row.status})")
    return {
        "still_frame_id": still.id,
        "t_sec": still.t_sec,
        # conf는 화면이 쓰지 않아 뺀다 (D-65)
        "detections": [{"det_id": d["det_id"], "bbox": d["bbox"]} for d in still.detections],
        "image_url": storage.make_view_url(
            still.masked_s3_key, expires_at or row.now + timedelta(days=VIEW_DAYS)
        ),
    }
