import json
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from sqlalchemy import text

from app import jobs, storage
from app.auth import current_user
from app.db import get_engine
from app.errors import ApiError
from app.videos import _owned_video, _view_expires_at

router = APIRouter(prefix="/api/videos")

PHOTO_EXT = ("jpg", "jpeg", "png", "heic")  # 01장 1.6, D-83
SCHEMA_VERSION = 5  # 05장 5.7, D-99


class PhotoBody(BaseModel):
    filename: str = Field(min_length=1)
    size_bytes: int = Field(gt=0)


class Vehicle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    det_id: StrictInt


class Damage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visible: StrictBool
    damage_bbox: list[StrictInt]
    floor_corners: list[list[StrictInt]]
    damage_edges: list[StrictInt]
    # 선택 키는 없으면 저장하지 않는다. null은 받지 않는다 (04장 damage_inputs)
    description: str = Field(default=None, min_length=1, max_length=500)
    photo_key: str = Field(default=None)


class InputBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    still_frame_id: StrictInt
    schema_version: Literal[5]
    vehicle: Vehicle
    damage: Damage


def _check_raw_alive(row, expires_at) -> None:
    """원본이 파기됐거나 열람기한이 지났으면 거절한다 (D-92, D-102)."""
    if row.raw_deleted_at is not None or (expires_at is not None and row.now > expires_at):
        raise ApiError(409, "RAW_EXPIRED", "raw video was deleted or the viewing period ended")


def _invalid(message: str) -> ApiError:
    return ApiError(422, "VALIDATION_FAILED", message)


def _cross(o, a, b) -> int:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _on_segment(p, q, r) -> bool:
    return min(p[0], q[0]) <= r[0] <= max(p[0], q[0]) and min(p[1], q[1]) <= r[1] <= max(p[1], q[1])


def _segments_meet(p1, p2, p3, p4) -> bool:
    """두 선분이 만나는지. 끝점이 닿거나 겹쳐도 만난 것으로 본다."""
    d1, d2 = _cross(p3, p4, p1), _cross(p3, p4, p2)
    d3, d4 = _cross(p1, p2, p3), _cross(p1, p2, p4)
    if ((d1 > 0) != (d2 > 0)) and d1 and d2 and ((d3 > 0) != (d4 > 0)) and d3 and d4:
        return True
    return (
        (d1 == 0 and _on_segment(p3, p4, p1))
        or (d2 == 0 and _on_segment(p3, p4, p2))
        or (d3 == 0 and _on_segment(p1, p2, p3))
        or (d4 == 0 and _on_segment(p1, p2, p4))
    )


def _check_geometry(damage: Damage, vehicle_bbox: list[int], width: int, height: int) -> None:
    box = damage.damage_bbox
    if len(box) != 4:
        raise _invalid("damage.damage_bbox must have 4 integers")
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise _invalid("damage.damage_bbox is outside the video frame")
    vx1, vy1, vx2, vy2 = vehicle_bbox
    if not (vx1 <= x1 and vy1 <= y1 and x2 <= vx2 and y2 <= vy2):
        raise _invalid("damage.damage_bbox is outside the selected vehicle")

    corners = damage.floor_corners
    if len(corners) != 4 or any(len(c) != 2 for c in corners):
        raise _invalid("damage.floor_corners must have 4 points")
    if any(not (0 <= x <= width and 0 <= y <= height) for x, y in corners):
        raise _invalid("damage.floor_corners is outside the video frame")
    if len({tuple(c) for c in corners}) != 4:
        raise _invalid("damage.floor_corners has a repeated point")
    c0, c1, c2, c3 = corners
    if _segments_meet(c0, c1, c2, c3) or _segments_meet(c1, c2, c3, c0):
        raise _invalid("damage.floor_corners makes a twisted quadrilateral")

    edges = damage.damage_edges
    if not 1 <= len(edges) <= 2 or any(not 0 <= e <= 3 for e in edges):
        raise _invalid("damage.damage_edges must be one or two edge numbers from 0 to 3")
    if len(edges) == 2 and abs(edges[0] - edges[1]) not in (1, 3):
        raise _invalid("damage.damage_edges must be neighboring edges")


@router.post("/{video_id}/input/photo")
def photo_upload_url(video_id: int, body: PhotoBody, user: Annotated[dict, Depends(current_user)]):
    ext = body.filename.rsplit(".", 1)[-1].lower() if "." in body.filename else ""
    if ext not in PHOTO_EXT:
        raise ApiError(422, "UNSUPPORTED_FILE_TYPE", "unsupported file type")
    if body.size_bytes > storage.MAX_PHOTO_BYTES:
        raise ApiError(422, "FILE_TOO_LARGE", "file is too large")
    with get_engine().connect() as conn:
        row = _owned_video(conn, video_id, user["id"])
    expires_at = _view_expires_at(row.upload_completed_at)
    _check_raw_alive(row, expires_at)
    if row.status != "stage1_done" or row.input_completed_at is not None:
        raise ApiError(409, "INVALID_STATE", f"input is not accepted (status: {row.status})")
    key = f"videos/{video_id}/inputs/photo.{ext}"
    return {
        "upload_url": storage.make_photo_upload_url(key, body.size_bytes, expires_at),
        "photo_key": key,
    }


@router.put("/{video_id}/input")
def save_input(video_id: int, body: InputBody, user: Annotated[dict, Depends(current_user)]):
    with get_engine().begin() as conn:
        row = _owned_video(conn, video_id, user["id"])
        expires_at = _view_expires_at(row.upload_completed_at)
        _check_raw_alive(row, expires_at)
        # 같은 입력이 동시에 두 번 와도 한쪽만 통과하게 작업 행을 잠근다 (D-46)
        job = conn.execute(
            text("SELECT status, input_completed_at FROM analysis_jobs WHERE id = :j FOR UPDATE"),
            {"j": row.job_id},
        ).one()
        if job.input_completed_at is not None:
            raise ApiError(409, "INVALID_STATE", f"input was already saved (status: {job.status})")
        if job.status != "stage1_done":
            raise ApiError(409, "INVALID_STATE", f"input is not accepted (status: {job.status})")

        still = conn.execute(
            text("SELECT detections FROM still_frames WHERE id = :s AND analysis_job_id = :j"),
            {"s": body.still_frame_id, "j": row.job_id},
        ).one_or_none()
        if still is None:
            raise _invalid("still_frame_id is not a still frame of this video")
        detection = next((d for d in still.detections if d["det_id"] == body.vehicle.det_id), None)
        if detection is None:
            raise _invalid("vehicle.det_id is not in the detections")
        size = conn.execute(
            text("SELECT width, height FROM videos WHERE id = :v"), {"v": video_id}
        ).one()
        if size.width is None or size.height is None:
            raise ApiError(409, "INVALID_STATE", "video size is not known yet")
        _check_geometry(body.damage, detection["bbox"], size.width, size.height)

        photo_key = body.damage.photo_key
        if photo_key is not None:
            pattern = rf"videos/{video_id}/inputs/photo\.({'|'.join(PHOTO_EXT)})"
            if not re.fullmatch(pattern, photo_key):
                raise _invalid("damage.photo_key is not a photo key of this video")

        vehicle_payload = {"det_id": detection["det_id"], "bbox": detection["bbox"]}
        damage_payload = body.damage.model_dump(exclude_unset=True)
        conn.execute(
            text(
                "INSERT INTO vehicle_selections (analysis_job_id, still_frame_id, schema_version, payload) "
                "VALUES (:j, :s, :v, CAST(:p AS jsonb))"
            ),
            {
                "j": row.job_id,
                "s": body.still_frame_id,
                "v": SCHEMA_VERSION,
                "p": json.dumps(vehicle_payload),
            },
        )
        conn.execute(
            text(
                "INSERT INTO damage_inputs (analysis_job_id, schema_version, payload) "
                "VALUES (:j, :v, CAST(:p AS jsonb))"
            ),
            {"j": row.job_id, "v": SCHEMA_VERSION, "p": json.dumps(damage_payload)},
        )
        conn.execute(
            text(
                "UPDATE analysis_jobs SET input_completed_at = now(), updated_at = now() "
                "WHERE id = :j"
            ),
            {"j": row.job_id},
        )
        # 넣기에 실패하면 예외로 롤백한다. 입력은 저장되지 않는다 (05장 11번)
        jobs.send_job(row.job_id, "stage2")
    jobs.start_gpu()
    return {"status": "stage1_done", "input_done": True}
