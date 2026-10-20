from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import text

from app import access_log, jobs, storage
from app.auth import current_user
from app.db import get_engine
from app.errors import ApiError
from app.uploads import _iso
from app.videos import VIEW_DAYS, _owned_video, _view_expires_at

router = APIRouter(prefix="/api/videos")

ListKind = Literal["main", "parse_failed"]

# 목록마다 "지금 보여주는 묶음" 칼럼이 다르다. 고정된 두 값만 쓴다
_CURRENT = {"main": "current_batch_no", "parse_failed": "current_failed_batch_no"}

# 그 목록의 묶음 n이 아직 만들어지는 중인지: 번호가 매겨지기 전이거나 클립이 pending·running이다
_BUILDING = (
    "SELECT NOT EXISTS (SELECT 1 FROM candidates WHERE analysis_job_id = :j AND list_kind = :k "
    "AND batch_no = :n) OR EXISTS (SELECT 1 FROM candidate_clips c "
    "JOIN candidates d ON d.id = c.candidate_id "
    "WHERE d.analysis_job_id = :j AND d.list_kind = :k AND d.batch_no = :n "
    "AND c.status IN ('pending', 'running'))"
)


class NextBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    list_kind: ListKind = Field(alias="list")
    batch_no: StrictInt = Field(ge=1)


_JOB = (
    "SELECT id, status, current_batch_no, current_failed_batch_no FROM analysis_jobs "
    "WHERE video_id = :v"
)


def _job(conn, video_id: int, lock: bool = False):
    return conn.execute(text(_JOB + " FOR UPDATE" if lock else _JOB), {"v": video_id}).one()


def _latest(conn, job, kind: str) -> int | None:
    """그 목록에서 볼 수 있는 마지막 묶음 번호. 만드는 중인 묶음은 뺀다 (05장 12번)."""
    current = job.current_batch_no if kind == "main" else job.current_failed_batch_no
    if current is None:
        return None
    if (
        job.status == "batch_running"
        and conn.execute(text(_BUILDING), {"j": job.id, "k": kind, "n": current}).scalar_one()
    ):
        return current - 1 or None
    return current


def _lists(conn, job) -> dict:
    counts = {
        row.list_kind: row
        for row in conn.execute(
            text(
                "SELECT list_kind, "
                "count(*) FILTER (WHERE verdict = 'unseen' AND (batch_no IS NULL OR batch_no > "
                "CASE list_kind WHEN 'main' THEN coalesce(:cur, 0) ELSE coalesce(:cur_failed, 0) END)) "
                "AS remaining, "
                "count(*) FILTER (WHERE verdict = 'unseen') AS unseen, "
                "count(*) FILTER (WHERE verdict = 'unavailable') AS unavailable "
                "FROM candidates WHERE analysis_job_id = :j AND verdict IN ('unseen', 'unavailable') "
                "GROUP BY list_kind"
            ),
            {"j": job.id, "cur": job.current_batch_no, "cur_failed": job.current_failed_batch_no},
        )
    }
    result = {}
    for kind in ("main", "parse_failed"):
        row = counts.get(kind)
        result[kind] = {
            "latest_batch_no": _latest(conn, job, kind),
            "remaining": row.remaining if row else 0,
            "done": (row.unseen == 0) if row else True,
            "unavailable": row.unavailable if row else 0,
        }
    return result


def _check_masked_alive(row, expires_at) -> None:
    if row.masked_deleted_at is not None or (expires_at is not None and row.now > expires_at):
        when = row.masked_deleted_at or expires_at
        raise ApiError(409, "MASKED_EXPIRED", f"masked files were deleted at {_iso(when)}")


def _invalid(message: str) -> ApiError:
    return ApiError(422, "VALIDATION_FAILED", message)


@router.get("/{video_id}/batch")
def get_batch(
    video_id: int,
    request: Request,
    user: Annotated[dict, Depends(current_user)],
    list_kind: Annotated[str, Query(alias="list")] = "main",
    batch_no: int | None = None,
):
    if list_kind not in _CURRENT:
        raise _invalid("list must be main or parse_failed")
    with get_engine().connect() as conn:
        row = _owned_video(conn, video_id, user["id"])
        expires_at = _view_expires_at(row.upload_completed_at)
        _check_masked_alive(row, expires_at)
        job = _job(conn, video_id)
        if job.status not in ("ready", "batch_running"):
            raise ApiError(409, "INVALID_STATE", f"batch is not available (status: {job.status})")
        lists = _lists(conn, job)
        latest = lists[list_kind]["latest_batch_no"]
        if latest is None:
            raise _invalid(f"list {list_kind} is empty")
        number = latest if batch_no is None else batch_no
        if not 1 <= number <= latest:
            raise _invalid(f"batch_no must be between 1 and {latest}")
        clips = conn.execute(
            text(
                "SELECT * FROM (SELECT DISTINCT ON (d.id) d.rank, d.vlm_score, c.id AS clip_id, "
                "c.start_sec, c.end_sec, c.masked_s3_key FROM candidates d "
                "JOIN candidate_clips c ON c.candidate_id = d.id AND c.status = 'done' "
                "WHERE d.analysis_job_id = :j AND d.list_kind = :k AND d.batch_no = :n "
                "ORDER BY d.id, c.id DESC) latest ORDER BY rank"
            ),
            {"j": job.id, "k": list_kind, "n": number},
        ).all()
        unavailable = conn.execute(
            text(
                "SELECT count(*) FROM candidates WHERE analysis_job_id = :j AND list_kind = :k "
                "AND batch_no = :n AND verdict = 'unavailable'"
            ),
            {"j": job.id, "k": list_kind, "n": number},
        ).scalar_one()
    valid_until = expires_at or row.now + timedelta(days=VIEW_DAYS)
    candidates = []
    for clip in clips:
        candidates.append(
            {
                "candidate_clip_id": clip.clip_id,
                "rank": clip.rank,
                "vlm_score": clip.vlm_score,
                "start_sec": clip.start_sec,
                "end_sec": clip.end_sec,
                "clip_url": storage.make_view_url(clip.masked_s3_key, valid_until),
            }
        )
        access_log.write_access_log(
            access_log.VIEW_CLIP, request, user_id=user["id"], video_id=video_id
        )
    return {
        "list": list_kind,
        "batch_no": number,
        "unavailable": unavailable,
        "candidates": candidates,
        "lists": lists,
    }


@router.post("/{video_id}/batch/next")
def next_batch(video_id: int, body: NextBody, user: Annotated[dict, Depends(current_user)]):
    kind, n = body.list_kind, body.batch_no
    send = False
    with get_engine().begin() as conn:
        row = _owned_video(conn, video_id, user["id"])
        expires_at = _view_expires_at(row.upload_completed_at)
        if row.raw_deleted_at is not None or (expires_at is not None and row.now > expires_at):
            raise ApiError(409, "RAW_EXPIRED", "raw video was deleted or the viewing period ended")
        job = _job(conn, video_id, lock=True)
        current = job.current_batch_no if kind == "main" else job.current_failed_batch_no
        if job.status != "ready" or current != n:
            raise ApiError(
                409,
                "INVALID_STATE",
                f"cannot move on (status: {job.status}, {kind} batch: {current})",
            )
        conn.execute(
            text(
                "UPDATE candidates SET verdict = 'not_found', verdict_at = now() "
                "WHERE analysis_job_id = :j AND list_kind = :k AND batch_no = :n "
                "AND verdict = 'unseen'"
            ),
            {"j": job.id, "k": kind, "n": n},
        )
        has_next = conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM candidates WHERE analysis_job_id = :j "
                "AND list_kind = :k AND batch_no = :n)"
            ),
            {"j": job.id, "k": kind, "n": n + 1},
        ).scalar_one()
        unnumbered = conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM candidates WHERE analysis_job_id = :j "
                "AND list_kind = :k AND batch_no IS NULL)"
            ),
            {"j": job.id, "k": kind},
        ).scalar_one()
        new_status = None
        if has_next or unnumbered:
            building = (
                has_next
                and conn.execute(text(_BUILDING), {"j": job.id, "k": kind, "n": n + 1}).scalar_one()
            )
            new_status = "batch_running" if building or not has_next else "ready"
        elif not conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM candidates WHERE analysis_job_id = :j "
                "AND verdict = 'unseen')"
            ),
            {"j": job.id},
        ).scalar_one():
            new_status = "exhausted"
        if new_status is not None:
            column = _CURRENT[kind]
            move = f", {column} = :n1" if new_status != "exhausted" else ""
            conn.execute(
                text(
                    f"UPDATE analysis_jobs SET status = :s{move}, updated_at = now() "  # noqa: S608
                    "WHERE id = :j AND status = 'ready'"
                ),
                {"s": new_status, "n1": n + 1, "j": job.id},
            )
        if unnumbered:
            send = True
            jobs.send_job(job.id, "next_batch")  # 실패하면 예외로 롤백한다 (500)
    if send:
        jobs.start_gpu()
    with get_engine().connect() as conn:
        fresh = _job(conn, video_id)
        return {"status": fresh.status, "lists": _lists(conn, fresh)}
