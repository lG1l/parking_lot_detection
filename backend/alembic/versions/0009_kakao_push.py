"""카카오 인증 가입·비밀번호 재설정 (D-356, D-357), 웹 푸시 (D-358)"""

from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN kakao_id bigint UNIQUE")
    op.execute("ALTER TABLE sessions ADD COLUMN password_reset_until timestamptz")
    op.execute("""
        CREATE TABLE kakao_pending (
          id            bigserial PRIMARY KEY,
          state_hash    text        NOT NULL UNIQUE,
          purpose       text        NOT NULL,        -- signup | reset
          user_id       bigint      REFERENCES users(id) ON DELETE CASCADE,
          login_id      text,
          password_hash text,
          name          text,
          role          text,
          expires_at    timestamptz NOT NULL,
          created_at    timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE push_subscriptions (
          id         bigserial PRIMARY KEY,
          session_id bigint      NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          endpoint   text        NOT NULL UNIQUE,
          p256dh     text        NOT NULL,
          auth       text        NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE push_events (
          video_id bigint      NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
          kind     text        NOT NULL,             -- done | failed | upload_unconfirmed
          event_at timestamptz NOT NULL,
          sent_at  timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (video_id, kind, event_at)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE push_events")
    op.execute("DROP TABLE push_subscriptions")
    op.execute("DROP TABLE kakao_pending")
    op.execute("ALTER TABLE sessions DROP COLUMN password_reset_until")
    op.execute("ALTER TABLE users DROP COLUMN kakao_id")
