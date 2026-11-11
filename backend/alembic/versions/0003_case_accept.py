"""피해자의 사건 초대 수락 (D-233)"""

from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.execute("ALTER TABLE cases ADD COLUMN accepted_at timestamptz")
    # 수락 단계 전에 만든 사건은 이미 묶인 것으로 본다
    op.execute("UPDATE cases SET accepted_at = created_at")


def downgrade() -> None:
    op.execute("ALTER TABLE cases DROP COLUMN accepted_at")
