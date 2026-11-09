"""Keep the latest presence timestamp after an authentication session ends."""

import sqlalchemy as sa

from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade():
    for account, sessions, foreign_key in (
        ("users", "login_sessions", "user_id"),
        ("inspectors", "inspection_sessions", "inspector_id"),
    ):
        op.add_column(account, sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
        op.execute(f"""
            UPDATE {account} AS account
            SET last_seen_at = activity.last_seen_at
            FROM (
                SELECT {foreign_key} AS id, MAX(last_seen_at) AS last_seen_at
                FROM {sessions}
                WHERE last_seen_at IS NOT NULL
                GROUP BY {foreign_key}
            ) AS activity
            WHERE account.id = activity.id
        """)


def downgrade():
    op.drop_column("inspectors", "last_seen_at")
    op.drop_column("users", "last_seen_at")
