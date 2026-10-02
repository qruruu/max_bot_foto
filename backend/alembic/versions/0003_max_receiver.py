"""Durable MAX polling checkpoint and delivery diagnostics."""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "max_receiver_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_fingerprint", sa.String(64)),
        sa.Column("marker", sa.BigInteger()),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_event_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(100)),
        sa.Column("events_received", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("inbox_received", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_table("max_receiver_state")
