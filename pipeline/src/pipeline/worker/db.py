"""워커가 쓰는 DB 코드 (D-361 나-2). 로컬·AWS 모드가 같은 코드를 쓴다.

SQL은 backend의 가짜 워커(backend/local/fake_worker.py)가 쓰는 것과 같은 자리·값·순서다.
상태를 바꾸는 UPDATE는 모두 "지금 상태가 맞을 때만" 바꾸는 조건부 UPDATE다 (04장 4.4).
"""

import json

from sqlalchemy import Engine, Row, create_engine, text


def make_engine(database_url: str) -> Engine:
    """DB 연결을 만드는 엔진. 주소는 backend와 같은 postgresql+psycopg://… 꼴이다."""
    return create_engine(database_url)


def read_job(engine: Engine, job_id: int) -> Row | None:
    """작업 행의 상태(status)·영상 번호(video_id)·원본 키(s3_key). 작업 행이 없으면 None이다."""
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT j.status, j.video_id, v.s3_key FROM analysis_jobs j "
                "JOIN videos v ON v.id = j.video_id WHERE j.id = :j"
            ),
            {"j": job_id},
        ).one_or_none()


def start_stage1(engine: Engine, job_id: int) -> bool:
    """queued → stills_running (전이 2). 다른 쪽이 먼저 바꿨으면 0행이라 False다."""
    # engine.begin()은 묶음 안의 SQL을 한 트랜잭션으로 실행하고, 오류가 나면 모두 되돌린다
    with engine.begin() as conn:
        moved = conn.execute(
            text(
                "UPDATE analysis_jobs SET status = 'stills_running', stage1_started_at = now(), "
                "updated_at = now() WHERE id = :j AND status = 'queued'"
            ),
            {"j": job_id},
        ).rowcount  # rowcount는 UPDATE가 바꾼 행 수다
    return moved == 1


def write_stage1_result(
    engine: Engine,
    job_id: int,
    video_id: int,
    video_info: dict,
    masked_key: str,
    detections: list[dict],
) -> bool:
    """stills_running → stage1_done (전이 3)과 1단계 결과를 한 트랜잭션으로 쓴다.

    상태가 바뀐 경우(1행)에만 영상 정보와 정지 장면 행을 쓴다. 바뀌지 않았으면 False다.
    video_info는 duration_sec·fps·width·height를 가진다.
    """
    with engine.begin() as conn:
        moved = conn.execute(
            text(
                "UPDATE analysis_jobs SET status = 'stage1_done', stage1_ended_at = now(), "
                "updated_at = now() WHERE id = :j AND status = 'stills_running'"
            ),
            {"j": job_id},
        ).rowcount
        if moved != 1:
            return False
        conn.execute(
            text(
                "UPDATE videos SET duration_sec = :duration_sec, fps = :fps, "
                "width = :width, height = :height WHERE id = :v"
            ),
            {"v": video_id, **video_info},
        )
        conn.execute(
            text(
                "INSERT INTO still_frames (analysis_job_id, t_sec, masked_s3_key, detections) "
                "VALUES (:j, 0.0, :k, CAST(:d AS jsonb)) ON CONFLICT (analysis_job_id) DO NOTHING"
            ),
            {"j": job_id, "k": masked_key, "d": json.dumps(detections)},
        )
    return True
