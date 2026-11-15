"""후보가 클립 구간·트랙 번호·후보 구간·유력 시점을 가진다 (D-280, D-281, D-282)"""

from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE candidates "
        "ADD COLUMN start_sec double precision, "
        "ADD COLUMN end_sec double precision, "
        "ADD COLUMN track_ids integer[], "
        "ADD COLUMN motion_ranges jsonb, "
        "ADD COLUMN likely_moments jsonb"
    )
    # 기존 행은 지우지 않고 채운다. 가짜 워커가 쓰던 계산식(judged_at_sec ± 15)이다 (D-282)
    op.execute(
        "UPDATE candidates SET start_sec = judged_at_sec - 15, end_sec = judged_at_sec + 15, "
        "track_ids = ARRAY[track_id], motion_ranges = '[]', likely_moments = '[]'"
    )
    op.execute(
        "ALTER TABLE candidates "
        "ALTER COLUMN start_sec SET NOT NULL, "
        "ALTER COLUMN end_sec SET NOT NULL, "
        "ALTER COLUMN track_ids SET NOT NULL, "
        "ALTER COLUMN motion_ranges SET NOT NULL, "
        "ALTER COLUMN likely_moments SET NOT NULL, "
        "DROP COLUMN judged_at_sec, "
        "DROP COLUMN channel, "
        "DROP COLUMN rule_name, "
        "DROP COLUMN track_id"
    )
    op.execute("ALTER TABLE candidate_clips DROP COLUMN start_sec, DROP COLUMN end_sec")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE candidate_clips "
        "ADD COLUMN start_sec double precision, ADD COLUMN end_sec double precision"
    )
    op.execute(
        "UPDATE candidate_clips c SET start_sec = d.start_sec, end_sec = d.end_sec "
        "FROM candidates d WHERE d.id = c.candidate_id"
    )
    op.execute(
        "ALTER TABLE candidate_clips "
        "ALTER COLUMN start_sec SET NOT NULL, ALTER COLUMN end_sec SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE candidates "
        "ADD COLUMN judged_at_sec double precision, "
        "ADD COLUMN channel text, "
        "ADD COLUMN rule_name text, "
        "ADD COLUMN track_id integer"
    )
    # channel·rule_name은 복원할 수 없어 고정값으로 채운다 (D-282)
    op.execute(
        "UPDATE candidates SET judged_at_sec = start_sec + 15, channel = 'A', "
        "rule_name = 'unknown', track_id = track_ids[1]"
    )
    op.execute(
        "ALTER TABLE candidates "
        "ALTER COLUMN judged_at_sec SET NOT NULL, "
        "ALTER COLUMN channel SET NOT NULL, "
        "ALTER COLUMN rule_name SET NOT NULL, "
        "ALTER COLUMN track_id SET NOT NULL, "
        "DROP COLUMN start_sec, "
        "DROP COLUMN end_sec, "
        "DROP COLUMN track_ids, "
        "DROP COLUMN motion_ranges, "
        "DROP COLUMN likely_moments"
    )
