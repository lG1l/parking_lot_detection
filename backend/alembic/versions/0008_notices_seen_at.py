"""상대 사건의 알림을 어디까지 봤는지 (D-338)"""

from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.execute("ALTER TABLE chat_reads ADD COLUMN notices_seen_at timestamptz")
    # 알림만 보고 메시지는 안 읽은 행은 0이다
    op.execute("ALTER TABLE chat_reads ALTER COLUMN last_read_message_id SET DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE chat_reads ALTER COLUMN last_read_message_id DROP DEFAULT")
    op.execute("ALTER TABLE chat_reads DROP COLUMN notices_seen_at")
