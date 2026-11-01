"""관리자 주도 흐름: 사건·열람 동의·계정 역할, 업로드 링크 삭제 (D-204, 04장 4.10)"""

from alembic import op

revision = "0002"
down_revision = "0001"

UPGRADE = [
    # 옛 형식의 영상 데이터는 버린다 (D-25). access_logs는 video_id가 NULL이 되고 행은 남는다
    "DELETE FROM videos",
    "DELETE FROM upload_tokens",
    # 기존 계정은 링크로 영상을 받던 피해자 계정이었다
    "ALTER TABLE users ADD COLUMN role text",
    "UPDATE users SET role = 'victim'",
    "ALTER TABLE users ALTER COLUMN role SET NOT NULL",
    """
CREATE TABLE cases (
  id             bigserial PRIMARY KEY,
  admin_user_id  bigint      NOT NULL REFERENCES users(id),
  victim_user_id bigint      NOT NULL REFERENCES users(id),
  created_at     timestamptz NOT NULL DEFAULT now()
)
    """,
    "ALTER TABLE videos DROP COLUMN owner_user_id",
    "ALTER TABLE videos DROP COLUMN upload_token_id",
    "ALTER TABLE videos ADD COLUMN case_id bigint NOT NULL REFERENCES cases(id)",
    "ALTER TABLE upload_agreements DROP COLUMN upload_token_id",
    "ALTER TABLE upload_agreements "
    "ADD COLUMN video_id bigint NOT NULL UNIQUE REFERENCES videos(id) ON DELETE CASCADE",
    "DROP TABLE upload_tokens",
    """
CREATE TABLE viewing_agreements (
  id           bigserial PRIMARY KEY,
  video_id     bigint      NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  user_id      bigint      NOT NULL REFERENCES users(id),
  requested_ip inet        NOT NULL,
  agreed_at    timestamptz NOT NULL DEFAULT now()
)
    """,
    "CREATE INDEX idx_videos_case   ON videos (case_id, created_at DESC)",
    "CREATE INDEX idx_cases_admin   ON cases (admin_user_id, created_at DESC)",
    "CREATE INDEX idx_cases_victim  ON cases (victim_user_id, created_at DESC)",
    "CREATE INDEX idx_viewing_video ON viewing_agreements (video_id)",
]

# 구조만 되돌린다. 지운 데이터는 돌아오지 않는다
DOWNGRADE = [
    "DELETE FROM videos",
    "DROP TABLE viewing_agreements",
    """
CREATE TABLE upload_tokens (
  id            bigserial PRIMARY KEY,
  token_hash    text        NOT NULL UNIQUE,
  owner_user_id bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at    timestamptz NOT NULL,
  used_at       timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
)
    """,
    "ALTER TABLE upload_agreements DROP COLUMN video_id",
    "ALTER TABLE upload_agreements ADD COLUMN upload_token_id bigint NOT NULL UNIQUE "
    "REFERENCES upload_tokens(id) ON DELETE CASCADE",
    "ALTER TABLE videos DROP COLUMN case_id",
    "ALTER TABLE videos ADD COLUMN owner_user_id bigint NOT NULL REFERENCES users(id)",
    "ALTER TABLE videos "
    "ADD COLUMN upload_token_id bigint NOT NULL UNIQUE REFERENCES upload_tokens(id)",
    "CREATE INDEX idx_videos_owner ON videos (owner_user_id, created_at DESC)",
    "DROP TABLE cases",
    "ALTER TABLE users DROP COLUMN role",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
