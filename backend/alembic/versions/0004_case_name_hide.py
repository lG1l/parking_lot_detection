"""계정별 사건 이름과 사건 숨기기 (D-239, D-240)"""

from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cases "
        "ADD COLUMN admin_case_name text, "
        "ADD COLUMN victim_case_name text, "
        "ADD COLUMN admin_deleted_at timestamptz, "
        "ADD COLUMN victim_deleted_at timestamptz"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE cases "
        "DROP COLUMN admin_case_name, "
        "DROP COLUMN victim_case_name, "
        "DROP COLUMN admin_deleted_at, "
        "DROP COLUMN victim_deleted_at"
    )
