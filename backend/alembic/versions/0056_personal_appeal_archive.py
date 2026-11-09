"""Give each staff member and inspector a personal appeal archive."""

import sqlalchemy as sa
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "personal_appeal_archives",
        sa.Column("appeal_id", sa.Integer(), sa.ForeignKey("citizen_appeals.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("actor_type", sa.String(30), primary_key=True),
        sa.Column("actor_id", sa.String(36), primary_key=True),
    )
    op.execute("""
        INSERT INTO personal_appeal_archives (appeal_id, actor_type, actor_id)
        SELECT a.id,
            CASE WHEN e.actor_type = 'ORGANIZATION_USER' AND o.legacy
                AND e.actor_id = CAST(o.owner_user_id AS TEXT) THEN 'OWNER'
                ELSE e.actor_type END,
            e.actor_id
        FROM citizen_appeals a
        LEFT JOIN organizations o ON o.id = a.organization_id
        JOIN LATERAL (
            SELECT actor_type, actor_id
            FROM appeal_events
            WHERE appeal_id = a.id AND kind = 'ARCHIVED'
            ORDER BY id DESC LIMIT 1
        ) e ON true
        WHERE a.archived_at IS NOT NULL AND e.actor_id <> ''
    """)
    op.execute("UPDATE citizen_appeals SET archived_at = NULL WHERE archived_at IS NOT NULL")


def downgrade():
    raise RuntimeError("Personal archive state cannot be safely converted to a shared archive.")
