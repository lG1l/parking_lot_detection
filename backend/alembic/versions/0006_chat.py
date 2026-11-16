"""채팅 메시지와 읽은 위치 (D-285, D-289)"""

from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.execute(
        "CREATE TABLE chat_messages ("
        "  id             bigserial PRIMARY KEY,"
        "  admin_user_id  bigint      NOT NULL REFERENCES users(id),"
        "  victim_user_id bigint      NOT NULL REFERENCES users(id),"
        "  sender_user_id bigint      NOT NULL REFERENCES users(id),"
        "  body           text        NOT NULL,"
        "  created_at     timestamptz NOT NULL DEFAULT now()"
        ")"
    )
    op.execute("CREATE INDEX idx_chat_pair ON chat_messages (admin_user_id, victim_user_id, id)")
    op.execute(
        "CREATE TABLE chat_reads ("
        "  user_id              bigint      NOT NULL REFERENCES users(id),"
        "  peer_user_id         bigint      NOT NULL REFERENCES users(id),"
        # FK 없음. 메시지가 지워져도 남는다 (D-288)
        "  last_read_message_id bigint      NOT NULL,"
        "  updated_at           timestamptz NOT NULL DEFAULT now(),"
        "  PRIMARY KEY (user_id, peer_user_id)"
        ")"
    )


def downgrade() -> None:
    op.execute("DROP TABLE chat_reads")
    op.execute("DROP TABLE chat_messages")
