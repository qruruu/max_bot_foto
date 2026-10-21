"""Unified sign-in directory, short-lived choices and reusable Disk accounts."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("disk_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("yandex_uid", sa.String(100), nullable=False, unique=True),
        sa.Column("login", sa.String(150), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("organizations", sa.Column("disk_account_id", sa.String(36), sa.ForeignKey("disk_accounts.id")))
    op.create_table("organization_logins",
        sa.Column("login", sa.String(100), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False))
    op.create_table("workspace_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_workspace_sessions_organization_id", "workspace_sessions", ["organization_id"])
    op.create_index("ix_workspace_sessions_expires_at", "workspace_sessions", ["expires_at"])
    op.create_table("login_choices",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("csrf_hash", sa.String(64), nullable=False), sa.Column("ip_hash", sa.String(64), nullable=False),
        sa.Column("candidates", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_login_choices_expires_at", "login_choices", ["expires_at"])


def downgrade():
    raise RuntimeError("Restore a coordinated backup to preserve organization access and storage settings.")
