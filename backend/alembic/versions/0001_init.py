"""init schema (04장 4.10)"""

from alembic import op

revision = "0001"
down_revision = None

STATEMENTS = [
    """
CREATE TABLE users (
  id            bigserial PRIMARY KEY,
  login_id      text        NOT NULL UNIQUE,
  password_hash text        NOT NULL,
  name          text        NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
)
    """,
    """
CREATE TABLE sessions (
  id         bigserial PRIMARY KEY,
  token_hash text        NOT NULL UNIQUE,   -- HttpOnly 쿠키에 담기는 랜덤 문자열의 SHA-256 (64자)
  user_id    bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
)
    """,
    """
CREATE TABLE upload_tokens (
  id            bigserial PRIMARY KEY,
  token_hash    text        NOT NULL UNIQUE,   -- 링크 주소에 들어가는 랜덤 문자열의 SHA-256 (64자)
  owner_user_id bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at    timestamptz NOT NULL,
  used_at       timestamptz,                   -- 비어 있지 않으면 이미 쓴 링크
  created_at    timestamptz NOT NULL DEFAULT now()
)
    """,
    """
CREATE TABLE upload_agreements (
  id                        bigserial PRIMARY KEY,
  upload_token_id           bigint      NOT NULL UNIQUE REFERENCES upload_tokens(id) ON DELETE CASCADE,
  agreement_version         text        NOT NULL,   -- 동의한 계약 문구 버전 (법적문제검토 4부)
  confirm_signage           boolean     NOT NULL,
  confirm_disclosure_judged boolean     NOT NULL,
  confirm_reconsignment     boolean     NOT NULL,
  requested_ip              inet        NOT NULL,   -- 접속 IP
  agreed_at                 timestamptz NOT NULL DEFAULT now()   -- 90일 뒤 주기 작업이 지운다 (D-147)
)
    """,
    """
CREATE TABLE videos (
  id                  bigserial PRIMARY KEY,
  owner_user_id       bigint      NOT NULL REFERENCES users(id),
  upload_token_id     bigint      NOT NULL UNIQUE REFERENCES upload_tokens(id),  -- 영상은 링크로만 올라온다 (D-45). 링크 하나에 영상 하나 (D-108)
  s3_key              text        NOT NULL,
  original_filename   text        NOT NULL,
  recording_started_at timestamptz,            -- 관리자가 입력한 녹화 시작 시각. 선택 (D-85)
  size_bytes          bigint,                  -- 업로드 URL 발급 때 채운다
  duration_sec        double precision,        -- 아래 4개는 워커가 1단계에서 채운다
  fps                 double precision,
  width               integer,
  height              integer,
  created_at          timestamptz NOT NULL DEFAULT now(),
  upload_completed_at timestamptz,             -- 비어 있으면 업로드 미완료
  raw_deleted_at      timestamptz,             -- 원본과 트랙을 파기 처리한 시각. 비어 있으면 파기 전 (D-52, D-64, D-142)
  masked_deleted_at   timestamptz              -- 마스킹본을 파기 처리한 시각. raw_deleted_at과 같은 때 찍는다 (D-57, D-64, D-142)
)
    """,
    """
CREATE TABLE analysis_jobs (
  id                 bigserial PRIMARY KEY,
  video_id           bigint      NOT NULL UNIQUE REFERENCES videos(id) ON DELETE CASCADE,
  status             text        NOT NULL,     -- 값 목록은 4.3
  stage1_started_at  timestamptz,
  stage1_ended_at    timestamptz,
  stage2_started_at  timestamptz,
  stage2_ended_at    timestamptz,
  input_completed_at timestamptz,
  error_message      text,
  failure_kind       text CHECK (failure_kind IN ('input_error','vlm_parse_rate','vlm_outage','worker_died')),  -- D-112
  user_retry_count   integer     NOT NULL DEFAULT 0 CHECK (user_retry_count BETWEEN 0 AND 3),  -- D-112
  processed_sec      double precision NOT NULL DEFAULT 0,   -- 중간 저장한 지점 (D-76)
  current_batch_no   integer,                  -- 후보군 목록의 지금 보여주는 묶음. ready가 될 때 1 (D-82)
  current_failed_batch_no integer,             -- 파싱 실패 목록의 지금 보여주는 묶음. 없으면 비어 있다 (D-99)
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
)
    """,
    """
CREATE TABLE still_frames (
  id              bigserial PRIMARY KEY,
  analysis_job_id bigint           NOT NULL UNIQUE REFERENCES analysis_jobs(id) ON DELETE CASCADE,   -- 작업당 1장 (D-48)
  t_sec           double precision NOT NULL,   -- 시작 장면이라 0.0
  masked_s3_key   text             NOT NULL,   -- 마스킹본만 저장한다 (불변 조건 2)
  detections      jsonb            NOT NULL,   -- 탐지된 차량 목록. 0건이면 [] (D-65)
  created_at      timestamptz      NOT NULL DEFAULT now()
)
    """,
    """
CREATE TABLE vehicle_selections (
  id              bigserial PRIMARY KEY,
  analysis_job_id bigint      NOT NULL UNIQUE REFERENCES analysis_jobs(id) ON DELETE CASCADE,
  still_frame_id  bigint      NOT NULL REFERENCES still_frames(id),
  schema_version  integer     NOT NULL,
  payload         jsonb       NOT NULL,        -- 검증은 백엔드가 한다 (D-25)
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
)
    """,
    """
CREATE TABLE damage_inputs (
  id              bigserial PRIMARY KEY,
  analysis_job_id bigint      NOT NULL UNIQUE REFERENCES analysis_jobs(id) ON DELETE CASCADE,
  schema_version  integer     NOT NULL,
  payload         jsonb       NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
)
    """,
    """
CREATE TABLE candidates (
  id              bigserial PRIMARY KEY,
  analysis_job_id bigint           NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
  judged_at_sec   double precision NOT NULL,   -- 구간은 저장하지 않는다 (D-33). VLM 기준점 (D-84)
  channel         text             NOT NULL,   -- 'A' | 'B' (D-71). 합친 후보의 값은 🚧 (U-13)
  rule_name       text             NOT NULL,   -- 목록은 🚧 (U-13)
  track_id        integer          NOT NULL,   -- 영상 안에서 유일 (4.8, D-76)
  vlm_pass1       boolean,                     -- 1차 VLM 통과/탈락. 1차 전·건너뜀은 비어 있다 (D-74)
  vlm_score       integer,                     -- 0~100. 1차 탈락은 0. VLM 호출 전과 2차 파싱 실패는 비어 있다 (D-93)
  list_kind       text             NOT NULL DEFAULT 'main',   -- 'main' | 'parse_failed' (D-99)
  rank            integer,                     -- 목록마다 1부터
  batch_no        integer,                     -- 목록마다 1부터
  verdict         text             NOT NULL DEFAULT 'unseen',   -- 'unseen' | 'not_found'. 찾음은 pinned_incidents (D-35)
  verdict_at      timestamptz,
  created_at      timestamptz      NOT NULL DEFAULT now()
)
    """,
    """
CREATE TABLE candidate_clips (
  id            bigserial PRIMARY KEY,
  candidate_id  bigint           NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,   -- 묶음 번호는 후보에서 (D-33)
  start_sec     double precision NOT NULL,
  end_sec       double precision NOT NULL,
  masked_s3_key text,                          -- 완료 후 채운다
  crop_bbox     integer[],                     -- [x1, y1, x2, y2] 원본 픽셀. 클립을 만들 때 채운다 (D-70, D-84)
  status        text             NOT NULL DEFAULT 'pending',
  created_at    timestamptz      NOT NULL DEFAULT now()
)
    """,
    """
CREATE TABLE pinned_incidents (
  id                bigserial PRIMARY KEY,
  analysis_job_id   bigint      NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
  candidate_clip_id bigint      NOT NULL REFERENCES candidate_clips(id),   -- CASCADE 없음 (D-32)
  pinned_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (analysis_job_id, candidate_clip_id)                              -- 작업당 여러 개 (D-80)
)
    """,
    """
CREATE TABLE access_logs (
  id           bigserial PRIMARY KEY,
  user_id      bigint      REFERENCES users(id)  ON DELETE SET NULL,   -- 시스템 기록은 NULL
  video_id     bigint      REFERENCES videos(id) ON DELETE SET NULL,   -- login 등은 NULL
  action       text        NOT NULL,             -- 값 목록은 4.2, 코드 enum으로 관리 (D-27)
  requested_ip inet,
  created_at   timestamptz NOT NULL DEFAULT now()
)
    """,
    """
CREATE INDEX idx_videos_owner        ON videos (owner_user_id, created_at DESC)
    """,
    """
CREATE INDEX idx_jobs_status_created ON analysis_jobs (status, created_at)
    """,
    """
CREATE INDEX idx_cand_job_batch_rank ON candidates (analysis_job_id, list_kind, batch_no, rank)
    """,
    """
CREATE INDEX idx_cand_job_verdict    ON candidates (analysis_job_id, verdict)
    """,
    """
CREATE INDEX idx_clips_candidate     ON candidate_clips (candidate_id)
    """,
    """
CREATE INDEX idx_access_video        ON access_logs (video_id, created_at DESC)
    """,
    """
CREATE INDEX idx_videos_raw_alive    ON videos (upload_completed_at) WHERE raw_deleted_at IS NULL
    """,
    """
CREATE INDEX idx_videos_masked_alive ON videos (upload_completed_at) WHERE masked_deleted_at IS NULL
    """,
]

TABLES = [
    "access_logs",
    "pinned_incidents",
    "candidate_clips",
    "candidates",
    "damage_inputs",
    "vehicle_selections",
    "still_frames",
    "analysis_jobs",
    "videos",
    "upload_agreements",
    "upload_tokens",
    "sessions",
    "users",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TABLE {table}")
