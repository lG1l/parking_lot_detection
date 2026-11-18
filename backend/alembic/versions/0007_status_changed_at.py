"""상태가 실제로 바뀐 시각. DB 트리거가 갱신한다 (D-334)"""

from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.execute("ALTER TABLE analysis_jobs ADD COLUMN status_changed_at timestamptz")
    # 기존 행은 updated_at으로 채운다
    op.execute("UPDATE analysis_jobs SET status_changed_at = updated_at")
    op.execute(
        "ALTER TABLE analysis_jobs "
        "ALTER COLUMN status_changed_at SET DEFAULT now(), "
        "ALTER COLUMN status_changed_at SET NOT NULL"
    )
    # 상태를 바꾸는 곳(API·워커)이 여러 곳이라 UPDATE마다 적지 않고 트리거로 한 곳에서 갱신한다
    op.execute(
        "CREATE FUNCTION set_status_changed_at() RETURNS trigger AS $$ "
        "BEGIN "
        "  IF NEW.status IS DISTINCT FROM OLD.status THEN NEW.status_changed_at := now(); END IF; "
        "  RETURN NEW; "
        "END $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER trg_status_changed_at BEFORE UPDATE ON analysis_jobs "
        "FOR EACH ROW EXECUTE FUNCTION set_status_changed_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_status_changed_at ON analysis_jobs")
    op.execute("DROP FUNCTION set_status_changed_at()")
    op.execute("ALTER TABLE analysis_jobs DROP COLUMN status_changed_at")
