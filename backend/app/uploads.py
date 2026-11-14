from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, Response
from pydantic import AwareDatetime, BaseModel, Field, StrictBool
from sqlalchemy import text

from app import jobs, storage
from app.access_log import client_ip
from app.auth import current_admin
from app.db import get_engine
from app.errors import ApiError

ALLOWED_EXT = ("mp4", "avi", "mkv", "mov")  # D-43
AGREEMENT_VERSION = "2026-11-01"  # 지금 계약 문구 버전 (D-147). 문구가 바뀌면 프론트와 함께 올린다
KST = ZoneInfo("Asia/Seoul")

router = APIRouter()


class Agreement(BaseModel):
    version: str | None = None
    confirm_signage: StrictBool | None = None
    confirm_disclosure_judged: StrictBool | None = None
    confirm_reconsignment: StrictBool | None = None


class PresignBody(BaseModel):
    filename: str = Field(min_length=1, pattern=r"^[^\x00]*$")
    size_bytes: int = Field(gt=0)
    recording_started_at: AwareDatetime | None = None
    agreement: Agreement | None = None


def _iso(value: datetime) -> str:
    return value.astimezone(KST).isoformat(timespec="seconds")


def _admin_video(conn, video_id: int, user_id: int) -> None:
    """로그인한 관리자의 사건에 속한 영상인지 본다. 아니면 다른 사건 영상도 없는 영상처럼 404."""
    found = conn.execute(
        text(
            "SELECT 1 FROM videos v JOIN cases c ON c.id = v.case_id "
            "WHERE v.id = :v AND c.admin_user_id = :u AND c.admin_deleted_at IS NULL"
        ),
        {"v": video_id, "u": user_id},
    ).first()
    if not found:
        raise ApiError(404, "VIDEO_NOT_FOUND", "video not found")


@router.post("/api/cases/{case_id}/uploads/presign")
def presign(
    case_id: int,
    body: PresignBody,
    request: Request,
    user: Annotated[dict, Depends(current_admin)],
):
    ext = body.filename.rsplit(".", 1)[-1].lower() if "." in body.filename else ""
    if ext not in ALLOWED_EXT:
        raise ApiError(422, "UNSUPPORTED_FILE_TYPE", "unsupported file type")
    if body.size_bytes > storage.MAX_UPLOAD_BYTES:
        raise ApiError(422, "FILE_TOO_LARGE", "file is too large")
    if body.recording_started_at and body.recording_started_at > datetime.now(UTC):
        raise ApiError(422, "VALIDATION_FAILED", "recording_started_at is in the future")
    a = body.agreement
    if not (
        a
        and a.version == AGREEMENT_VERSION
        and a.confirm_signage is True
        and a.confirm_disclosure_judged is True
        and a.confirm_reconsignment is True
    ):
        raise ApiError(422, "AGREEMENT_REQUIRED", "agreement is required")

    with get_engine().begin() as conn:
        found = conn.execute(
            text(
                "SELECT 1 FROM cases WHERE id = :c AND admin_user_id = :u "
                "AND admin_deleted_at IS NULL"
            ),
            {"c": case_id, "u": user["id"]},
        ).first()
        if not found:
            raise ApiError(404, "CASE_NOT_FOUND", "case not found")
        # 키에 영상 번호가 들어가므로 번호를 먼저 받는다 (04장 4.9)
        video_id = conn.execute(
            text("SELECT nextval(pg_get_serial_sequence('videos', 'id'))")
        ).scalar_one()
        key = f"videos/{video_id}/original.{ext}"
        conn.execute(
            text(
                "INSERT INTO videos (id, case_id, s3_key, original_filename, "
                "recording_started_at, size_bytes) VALUES (:id, :c, :k, :f, :r, :s)"
            ),
            {
                "id": video_id,
                "c": case_id,
                "k": key,
                "f": body.filename,
                "r": body.recording_started_at,
                "s": body.size_bytes,
            },
        )
        conn.execute(
            text(
                "INSERT INTO upload_agreements (video_id, agreement_version, "
                "confirm_signage, confirm_disclosure_judged, confirm_reconsignment, requested_ip) "
                "VALUES (:v, :ver, true, true, true, :ip)"
            ),
            {"v": video_id, "ver": a.version, "ip": client_ip(request)},
        )
    return {"video_id": video_id, "upload_url": storage.make_upload_url(key)}


@router.post("/api/videos/{video_id}/upload/complete", status_code=204)
def complete_upload(video_id: int, user: Annotated[dict, Depends(current_admin)]):
    with get_engine().begin() as conn:
        _admin_video(conn, video_id, user["id"])
        marked = conn.execute(
            text(
                "UPDATE videos SET upload_completed_at = now() "
                "WHERE id = :v AND upload_completed_at IS NULL RETURNING id"
            ),
            {"v": video_id},
        ).one_or_none()
        if marked is None:
            return Response(status_code=204)  # 이미 처리한 완료 알림
        job_id = conn.execute(
            text("INSERT INTO analysis_jobs (video_id, status) VALUES (:v, 'queued') RETURNING id"),
            {"v": video_id},
        ).scalar_one()
        # 05장 5.4의 7번: 넣기에 실패하면 롤백한다 (D-46, D-56)
        jobs.send_job(job_id, "stage1")
    jobs.start_gpu()
    return Response(status_code=204)


@router.post("/api/videos/{video_id}/upload/warmup", status_code=204)
def warmup(video_id: int, user: Annotated[dict, Depends(current_admin)]):
    with get_engine().connect() as conn:
        _admin_video(conn, video_id, user["id"])
        has_job = conn.execute(
            text("SELECT 1 FROM analysis_jobs WHERE video_id = :v"), {"v": video_id}
        ).first()
    if not has_job:  # 업로드 완료 뒤에는 켜지 않는다 (D-62)
        jobs.start_gpu()
    return Response(status_code=204)
