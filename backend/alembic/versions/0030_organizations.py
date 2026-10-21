"""Platform registry; existing company data stays in its original database."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("platform_max_receiver_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_fingerprint", sa.String(64)), sa.Column("marker", sa.BigInteger()),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_event_at", sa.DateTime(timezone=True)), sa.Column("last_error", sa.String(100)),
        sa.Column("events_received", sa.BigInteger(), nullable=False),
        sa.Column("inbox_received", sa.BigInteger(), nullable=False))
    op.create_table("organizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(60), unique=True, nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("database_name", sa.String(63), unique=True),
        sa.Column("database_role", sa.String(63), unique=True),
        sa.Column("owner_user_id", sa.Integer()), sa.Column("last_error", sa.String(80)),
        sa.Column("legacy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("platform_owners",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True))
    op.create_table("organization_chats",
        sa.Column("max_chat_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_organization_chats_organization_id", "organization_chats", ["organization_id"])
    op.create_table("organization_events",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("digest", sa.String(64), unique=True, nullable=False),
        sa.Column("max_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id")),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_error", sa.String(80)))
    for column in ("max_chat_id", "organization_id", "status"):
        op.create_index("ix_organization_events_" + column, "organization_events", [column])


def downgrade():
    raise RuntimeError("Organization boundaries must be preserved; restore a backup to roll back.")
