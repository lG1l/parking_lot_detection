from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, Response
from pydantic import AwareDatetime, BaseModel, Field, StrictBool
from sqlalchemy import text

from app import jobs, storage
from app.access_log import client_ip
from app.auth import current_user
from app.db import get_engine
from app.errors import ApiError
from app.security import new_token, token_hash

LINK_HOURS = 24  # 01장 1.6
ALLOWED_EXT = ("mp4", "avi", "mkv", "mov")  # D-43
AGREEMENT_VERSION = "2026-10-12"  # 지금 계약 문구 버전 (D-147). 문구가 바뀌면 프론트와 함께 올린다
KST = ZoneInfo("Asia/Seoul")

router = APIRouter()


class Agreement(BaseModel):
    version: str | None = None
    confirm_signage: StrictBool | None = None
    confirm_disclosure_judged: StrictBool | None = None
    confirm_reconsignment: StrictBool | None = None


class PresignBody(BaseModel):
    filename: str = Field(min_length=1)
    size_bytes: int = Field(gt=0)
    recording_started_at: AwareDatetime | None = None
    agreement: Agreement | None = None


def _iso(value: datetime) -> str:
    return value.astimezone(KST).isoformat(timespec="seconds")


def _link_error(conn, hash_: str) -> ApiError:
    """링크를 쓸 수 없는 이유를 코드로 알려준다. 사용됨이 만료보다 먼저다 (5.4)."""
    row = conn.execute(
        text(
            "SELECT used_at, expires_at <= now() AS expired FROM upload_tokens WHERE token_hash = :h"
        ),
        {"h": hash_},
    ).one_or_none()
    if row is None:
        return ApiError(404, "UPLOAD_TOKEN_NOT_FOUND", "upload link not found")
    if row.used_at is not None:
        return ApiError(410, "UPLOAD_TOKEN_USED", "upload link was already used")
    return ApiError(410, "UPLOAD_TOKEN_EXPIRED", "upload link expired")


def _used_link(conn, token: str):
    """6번 이후에 쓰는 링크 행(7·16번). 6번을 부른 적이 없으면 409."""
    row = conn.execute(
        text("SELECT id, used_at FROM upload_tokens WHERE token_hash = :h"),
        {"h": token_hash(token)},
    ).one_or_none()
    if row is None:
        raise ApiError(404, "UPLOAD_TOKEN_NOT_FOUND", "upload link not found")
    return row


@router.post("/api/upload-links", status_code=201)
def create_upload_link(user: Annotated[dict, Depends(current_user)]):
    token = new_token()
    with get_engine().begin() as conn:
        # 같은 사용자의 발급을 한 줄로 세워, 살아 있는 링크가 하나만 남게 한다 (D-103)
        conn.execute(text("SELECT id FROM users WHERE id = :u FOR UPDATE"), {"u": user["id"]})
        conn.execute(
            text(
                "UPDATE upload_tokens SET expires_at = now() "
                "WHERE owner_user_id = :u AND used_at IS NULL AND expires_at > now()"
            ),
            {"u": user["id"]},
        )
        expires_at = conn.execute(
            text(
                "INSERT INTO upload_tokens (token_hash, owner_user_id, expires_at) "
                "VALUES (:h, :u, now() + make_interval(hours => :n)) RETURNING expires_at"
            ),
            {"h": token_hash(token), "u": user["id"], "n": LINK_HOURS},
        ).scalar_one()
    return {"token": token, "expires_at": _iso(expires_at)}


@router.get("/api/uploads/{token}")
def check_upload_link(token: str):
    h = token_hash(token)
    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT expires_at FROM upload_tokens "
                "WHERE token_hash = :h AND used_at IS NULL AND expires_at > now()"
            ),
            {"h": h},
        ).one_or_none()
        if row is None:
            raise _link_error(conn, h)
    return {"expires_at": _iso(row.expires_at)}


@router.post("/api/uploads/{token}/presign")
def presign(token: str, body: PresignBody, request: Request):
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

    h = token_hash(token)
    with get_engine().begin() as conn:
        link = conn.execute(
            text(
                "UPDATE upload_tokens SET used_at = now() "
                "WHERE token_hash = :h AND used_at IS NULL AND expires_at > now() "
                "RETURNING id, owner_user_id"
            ),
            {"h": h},
        ).one_or_none()
        if link is None:
            raise _link_error(conn, h)
        conn.execute(
            text(
                "INSERT INTO upload_agreements (upload_token_id, agreement_version, "
                "confirm_signage, confirm_disclosure_judged, confirm_reconsignment, requested_ip) "
                "VALUES (:t, :v, true, true, true, :ip)"
            ),
            {"t": link.id, "v": a.version, "ip": client_ip(request)},
        )
        # 키에 영상 번호가 들어가므로 번호를 먼저 받는다 (04장 4.9)
        video_id = conn.execute(
            text("SELECT nextval(pg_get_serial_sequence('videos', 'id'))")
        ).scalar_one()
        key = f"videos/{video_id}/original.{ext}"
        conn.execute(
            text(
                "INSERT INTO videos (id, owner_user_id, upload_token_id, s3_key, "
                "original_filename, recording_started_at, size_bytes) "
                "VALUES (:id, :o, :t, :k, :f, :r, :s)"
            ),
            {
                "id": video_id,
                "o": link.owner_user_id,
                "t": link.id,
                "k": key,
                "f": body.filename,
                "r": body.recording_started_at,
                "s": body.size_bytes,
            },
        )
    return {"upload_url": storage.make_upload_url(key)}


@router.post("/api/uploads/{token}/complete", status_code=204)
def complete_upload(token: str):
    with get_engine().begin() as conn:
        link = _used_link(conn, token)
        video_id = conn.execute(
            text("SELECT id FROM videos WHERE upload_token_id = :t"), {"t": link.id}
        ).scalar_one_or_none()
        if video_id is None:
            raise ApiError(409, "INVALID_STATE", "upload was not started")
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


@router.post("/api/uploads/{token}/warmup", status_code=204)
def warmup(token: str):
    with get_engine().connect() as conn:
        link = _used_link(conn, token)
        if link.used_at is None:
            raise ApiError(409, "INVALID_STATE", "upload was not started")
        has_job = conn.execute(
            text(
                "SELECT 1 FROM analysis_jobs j JOIN videos v ON v.id = j.video_id "
                "WHERE v.upload_token_id = :t"
            ),
            {"t": link.id},
        ).first()
    if not has_job:
        jobs.start_gpu()
    return Response(status_code=204)
