from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, StrictBool
from sqlalchemy import text

from app import access_log, storage
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
SELECT v.id, v.case_id, v.original_filename, v.created_at, v.upload_completed_at, v.duration_sec,
       v.raw_deleted_at, v.masked_deleted_at, now() AS now,
       j.id AS job_id, j.failure_kind, j.user_retry_count, j.input_completed_at,
       {_STATUS} AS status
  FROM videos v JOIN cases c ON c.id = v.case_id
  LEFT JOIN analysis_jobs j ON j.video_id = v.id
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


def _masked_gone(row, expires_at: datetime | None) -> bool:
    """마스킹본을 더 볼 수 없는가. 파기 표시가 있거나 열람기한이 지났다 (D-187)"""
    return row.masked_deleted_at is not None or (expires_at is not None and row.now > expires_at)


# 피해자는 사건 초대를 수락해야 그 영상에 접근한다 (D-233, D-238)
# 내가 삭제(숨김)한 사건은 내 쪽에서만 없는 사건이 된다 (D-239)
_MEMBER = (
    "((c.admin_user_id = :u AND c.admin_deleted_at IS NULL) OR "
    "(c.victim_user_id = :u AND c.accepted_at IS NOT NULL AND c.victim_deleted_at IS NULL))"
)


def _case_video(conn, video_id: int, user: dict, role: str | None = None):
    """내가 묶인 사건의 영상만 준다. 사건 소속을 먼저 보고(404) 역할을 본다(403) (08장 8.7)"""
    row = conn.execute(
        text(_VIDEO + f" WHERE v.id = :v AND {_MEMBER}"),
        {"v": video_id, "u": user["id"]},
    ).one_or_none()
    if row is None:
        raise ApiError(404, "VIDEO_NOT_FOUND", "video not found")
    if role is not None and user["role"] != role:
        raise ApiError(403, "ROLE_NOT_ALLOWED", f"{role} account required")
    return row


def _viewing_video(conn, video_id: int, user: dict):
    """12·13·14·15·17번: 관리자 계정이고, 이 영상에 30분 안의 안내 동의가 있어야 한다 (D-205)"""
    row = _case_video(conn, video_id, user, "admin")
    agreed = conn.execute(
        text(
            "SELECT 1 FROM viewing_agreements "
            "WHERE video_id = :v AND agreed_at > now() - interval '30 minutes'"
        ),
        {"v": video_id},
    ).first()
    if not agreed:
        raise ApiError(403, "SUPERVISION_AGREEMENT_REQUIRED", "supervision agreement required")
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
    return "service", retry_left > 0  # vlm_parse_rate·worker_died (D-173)


@router.get("")
def list_videos(user: Annotated[dict, Depends(current_user)]):
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(_VIDEO + f" WHERE {_MEMBER} ORDER BY v.created_at DESC, v.id DESC"),
            {"u": user["id"]},
        ).all()
    result = []
    for row in rows:
        expires_at = _view_expires_at(row.upload_completed_at)
        result.append(
            {
                "video_id": row.id,
                "case_id": row.case_id,
                "original_filename": row.original_filename,
                "status": row.status,
                "created_at": _iso(row.created_at),
                "masked_deleted": _masked_gone(row, expires_at),
                "view_expires_at": _iso(expires_at) if expires_at else None,
            }
        )
    return result


@router.get("/{video_id}")
def get_video(video_id: int, user: Annotated[dict, Depends(current_user)]):
    with get_engine().connect() as conn:
        row = _case_video(conn, video_id, user)
        expires_at = _view_expires_at(row.upload_completed_at)
        input_done = row.input_completed_at is not None
        body = {
            "video_id": row.id,
            "original_filename": row.original_filename,
            "status": row.status,
            "input_done": input_done,
            "raw_deleted": row.raw_deleted_at is not None,
            "masked_deleted": _masked_gone(row, expires_at),
            "created_at": _iso(row.created_at),
            "duration_sec": row.duration_sec,
            "view_expires_at": _iso(expires_at) if expires_at else None,
        }
        if row.status == "queued" or (row.status == "stage1_done" and input_done):
            body["queue_ahead"] = conn.execute(
                text(_QUEUE_AHEAD), {"job_id": row.job_id}
            ).scalar_one()
        # 피해자 계정에는 후보 필드를 주지 않는다 (D-204)
        if row.status == "exhausted" and user["role"] == "admin":
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
def get_still(video_id: int, request: Request, user: Annotated[dict, Depends(current_user)]):
    with get_engine().connect() as conn:
        row = _case_video(conn, video_id, user, "victim")
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
    access_log.write_access_log(
        access_log.VIEW_STILL, request, user_id=user["id"], video_id=video_id
    )
    return {
        "still_frame_id": still.id,
        "t_sec": still.t_sec,
        # conf는 화면이 쓰지 않아 뺀다 (D-65). polygon은 차를 칠하고 고르는 데 쓴다 (D-221)
        "detections": [
            {"det_id": d["det_id"], "bbox": d["bbox"], "polygon": d["polygon"]}
            for d in still.detections
        ],
        "image_url": storage.make_view_url(
            still.masked_s3_key, expires_at or row.now + timedelta(days=VIEW_DAYS)
        ),
    }


class ViewingAgreementBody(BaseModel):
    confirm_supervision: StrictBool | None = None


@router.post("/{video_id}/viewing-agreement", status_code=204)
def agree_viewing(
    video_id: int,
    body: ViewingAgreementBody,
    request: Request,
    user: Annotated[dict, Depends(current_user)],
):
    with get_engine().begin() as conn:
        _case_video(conn, video_id, user, "admin")
        if body.confirm_supervision is not True:
            raise ApiError(422, "VALIDATION_FAILED", "confirm_supervision must be true")
        conn.execute(
            text(
                "INSERT INTO viewing_agreements (video_id, user_id, requested_ip) "
                "VALUES (:v, :u, :ip)"
            ),
            {"v": video_id, "u": user["id"], "ip": access_log.client_ip(request)},
        )
    access_log.write_access_log(
        access_log.AGREE_VIEWING, request, user_id=user["id"], video_id=video_id
    )
    return Response(status_code=204)
