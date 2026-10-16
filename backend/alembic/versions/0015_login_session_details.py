"""Expose revocable session IDs and record observed device/activity metadata."""

import sqlalchemy as sa

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "login_sessions",
        sa.Column("id", sa.String(36), server_default=sa.text("gen_random_uuid()::text"), nullable=False),
    )
    op.create_unique_constraint("uq_login_sessions_id", "login_sessions", ["id"])
    # Historical login times were never recorded. Keep them unknown rather than inventing them.
    op.add_column("login_sessions", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("login_sessions", "created_at", server_default=sa.func.now())
    op.add_column("login_sessions", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("login_sessions", sa.Column("user_agent", sa.String(512), nullable=True))
    op.add_column("login_sessions", sa.Column("ip_address", sa.String(45), nullable=True))


def downgrade():
    for column in ["ip_address", "user_agent", "last_seen_at", "created_at"]:
        op.drop_column("login_sessions", column)
    op.drop_constraint("uq_login_sessions_id", "login_sessions", type_="unique")
    op.drop_column("login_sessions", "id")
