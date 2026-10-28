from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, StrictInt
from sqlalchemy import text

from app import access_log, storage
from app.auth import current_user
from app.batches import _check_masked_alive
from app.db import get_engine
from app.errors import ApiError
from app.uploads import _iso
from app.videos import VIEW_DAYS, _owned_video, _view_expires_at

router = APIRouter(prefix="/api/videos")

OPEN_STATES = ("ready", "batch_running")


class PinBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_clip_id: StrictInt


def _pinned(conn, video_id: int, job_id: int | None, valid_until) -> list[dict]:
    """고정한 순서대로 (05장 15번). est_*_at은 녹화 시작 시각이 없으면 NULL이 된다 (D-85)."""
    rows = conn.execute(
        text(
            "SELECT c.id, c.start_sec, c.end_sec, c.masked_s3_key, p.pinned_at, "
            "v.recording_started_at + c.start_sec * interval '1 second' AS est_start, "
            "v.recording_started_at + c.end_sec * interval '1 second' AS est_end "
            "FROM pinned_incidents p JOIN candidate_clips c ON c.id = p.candidate_clip_id "
            "JOIN videos v ON v.id = :v WHERE p.analysis_job_id = :j "
            "ORDER BY p.pinned_at, p.id"
        ),
        {"v": video_id, "j": job_id},
    ).all()
    return [
        {
            "candidate_clip_id": r.id,
            "start_sec": r.start_sec,
            "end_sec": r.end_sec,
            "est_start_at": _iso(r.est_start) if r.est_start else None,
            "est_end_at": _iso(r.est_end) if r.est_end else None,
            "clip_url": storage.make_view_url(r.masked_s3_key, valid_until),
            "pinned_at": _iso(r.pinned_at),
        }
        for r in rows
    ]


def _list_pinned(video_id: int, job_id: int | None, request: Request, user_id: int, row) -> list:
    valid_until = _view_expires_at(row.upload_completed_at) or row.now + timedelta(days=VIEW_DAYS)
    with get_engine().connect() as conn:
        result = _pinned(conn, video_id, job_id, valid_until)
    for _ in result:
        access_log.write_access_log(
            access_log.VIEW_CLIP, request, user_id=user_id, video_id=video_id
        )
    return result


@router.post("/{video_id}/pin")
def pin(
    video_id: int,
    body: PinBody,
    request: Request,
    user: Annotated[dict, Depends(current_user)],
):
    with get_engine().begin() as conn:
        row = _owned_video(conn, video_id, user["id"])
        _check_masked_alive(row, _view_expires_at(row.upload_completed_at))
        found = conn.execute(
            text(
                "SELECT 1 FROM candidate_clips c JOIN candidates d ON d.id = c.candidate_id "
                "WHERE c.id = :c AND d.analysis_job_id = :j AND c.status = 'done'"
            ),
            {"c": body.candidate_clip_id, "j": row.job_id},
        ).first()
        if found is None:
            raise ApiError(404, "CLIP_NOT_FOUND", "clip not found")
        # FOR SHARE로 [확인 끝내기]·마지막 [다음]과 순서를 정한다 (04장, D-101)
        inserted = conn.execute(
            text(
                "INSERT INTO pinned_incidents (analysis_job_id, candidate_clip_id) "
                "SELECT :j, :c FROM analysis_jobs WHERE id = :j "
                "AND status IN ('ready', 'batch_running') FOR SHARE "
                "ON CONFLICT (analysis_job_id, candidate_clip_id) DO NOTHING"
            ),
            {"j": row.job_id, "c": body.candidate_clip_id},
        ).rowcount
        if not inserted:
            status = conn.execute(
                text("SELECT status FROM analysis_jobs WHERE id = :j"), {"j": row.job_id}
            ).scalar_one()
            if status not in OPEN_STATES:
                raise ApiError(409, "INVALID_STATE", f"cannot pin (status: {status})")
    if inserted:
        access_log.write_access_log(
            access_log.PIN_INCIDENT, request, user_id=user["id"], video_id=video_id
        )
    return _list_pinned(video_id, row.job_id, request, user["id"], row)


@router.delete("/{video_id}/pin/{candidate_clip_id}")
def unpin(
    video_id: int,
    candidate_clip_id: int,
    request: Request,
    user: Annotated[dict, Depends(current_user)],
):
    with get_engine().begin() as conn:
        row = _owned_video(conn, video_id, user["id"])
        _check_masked_alive(row, _view_expires_at(row.upload_completed_at))
        # FOR SHARE로 [확인 끝내기]·마지막 [다음]과 순서를 정한다 (D-101, D-181)
        status = conn.execute(
            text("SELECT status FROM analysis_jobs WHERE id = :j FOR SHARE"), {"j": row.job_id}
        ).scalar_one_or_none()
        if status not in OPEN_STATES:
            raise ApiError(409, "INVALID_STATE", f"cannot unpin (status: {status})")
        conn.execute(
            text(
                "DELETE FROM pinned_incidents WHERE analysis_job_id = :j AND candidate_clip_id = :c"
            ),
            {"j": row.job_id, "c": candidate_clip_id},
        )
    return _list_pinned(video_id, row.job_id, request, user["id"], row)


@router.get("/{video_id}/pin")
def get_pinned(video_id: int, request: Request, user: Annotated[dict, Depends(current_user)]):
    with get_engine().connect() as conn:
        row = _owned_video(conn, video_id, user["id"])
    _check_masked_alive(row, _view_expires_at(row.upload_completed_at))
    return _list_pinned(video_id, row.job_id, request, user["id"], row)


@router.post("/{video_id}/finish")
def finish(video_id: int, user: Annotated[dict, Depends(current_user)]):
    with get_engine().begin() as conn:
        _owned_video(conn, video_id, user["id"])
        # 14번의 고정(FOR SHARE)과 줄을 세운다 (D-101)
        job = conn.execute(
            text("SELECT id, status FROM analysis_jobs WHERE video_id = :v FOR UPDATE"),
            {"v": video_id},
        ).one_or_none()
        status = job.status if job else "uploading"
        if status not in OPEN_STATES:
            raise ApiError(409, "INVALID_STATE", f"cannot finish (status: {status})")
        pinned = conn.execute(
            text("SELECT 1 FROM pinned_incidents WHERE analysis_job_id = :j LIMIT 1"),
            {"j": job.id},
        ).first()
        if pinned is None:
            raise ApiError(409, "NO_PINNED_INCIDENTS", "no pinned incidents")
        conn.execute(
            text("UPDATE analysis_jobs SET status = 'finished', updated_at = now() WHERE id = :j"),
            {"j": job.id},
        )
    return {"status": "finished"}
