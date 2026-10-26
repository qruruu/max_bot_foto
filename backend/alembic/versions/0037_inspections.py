"""Independent inspector accounts, personal single-use invitations and private chats."""

import sqlalchemy as sa

from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
            for name in ("created_at", "updated_at")]


def upgrade():
    op.create_table("inspection_agencies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False), *timestamps())
    op.create_table("inspectors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.String(36), sa.ForeignKey("inspection_agencies.id"), nullable=False),
        sa.Column("login", sa.String(100), unique=True, nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("can_create_accounts", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("inspectors.id")), *timestamps())
    op.create_index("ix_inspectors_agency_id", "inspectors", ["agency_id"])
    op.create_table("inspection_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("inspector_id", sa.Integer(), sa.ForeignKey("inspectors.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    for key in ("inspector_id", "expires_at"):
        op.create_index("ix_inspection_sessions_" + key, "inspection_sessions", [key])
    op.create_table("inspection_qrs",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_by", sa.Integer(), sa.ForeignKey("inspectors.id")),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked", sa.Boolean(), nullable=False))
    op.create_index("ix_inspection_qrs_organization_id", "inspection_qrs", ["organization_id"])
    op.create_table("inspection_grants",
        sa.Column("inspector_id", sa.Integer(), sa.ForeignKey("inspectors.id"), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("inspection_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sender_key", sa.String(100), nullable=False),
        sa.Column("recipient_key", sa.String(100), nullable=False),
        sa.Column("client_id", sa.String(36), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("sender_key", "client_id", name="uq_inspection_message_client"),
        sa.CheckConstraint("sender_key <> recipient_key AND length(trim(body)) BETWEEN 1 AND 4000"))
    op.create_index("ix_inspection_messages_pair", "inspection_messages", ["sender_key", "recipient_key", "id"])


def downgrade():
    for name in ("inspection_messages", "inspection_grants", "inspection_qrs", "inspection_sessions",
                 "inspectors", "inspection_agencies"):
        op.drop_table(name)
