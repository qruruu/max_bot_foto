"""Private owner inbox and atomic camera submissions from citizens."""

import sqlalchemy as sa

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "citizen_appeals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("city", sa.String(150), nullable=False),
        sa.Column("address", sa.String(300), nullable=False),
        sa.Column("place", sa.String(300), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("organization_hint", sa.String(200), nullable=False),
        sa.Column("contact", sa.String(200), nullable=False),
        sa.Column("photo_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("owner_note", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('NEW', 'IN_REVIEW', 'RESOLVED', 'SPAM')"),
        sa.CheckConstraint("photo_count BETWEEN 1 AND 3"),
    )
    op.create_index("ix_citizen_appeals_status", "citizen_appeals", ["status"])
    op.create_table(
        "appeal_photos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("appeal_id", sa.Integer(), sa.ForeignKey("citizen_appeals.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("original", sa.LargeBinary(), nullable=False),
        sa.Column("stamped", sa.LargeBinary(), nullable=False),
        sa.Column("preview", sa.LargeBinary(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=False),
        sa.Column("position_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("appeal_id", "position"),
    )
    op.create_index("ix_appeal_photos_appeal_id", "appeal_photos", ["appeal_id"])
    op.create_table(
        "appeal_capture_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("appeal_id", sa.Integer(), sa.ForeignKey("citizen_appeals.id")),
    )
    op.create_index("ix_appeal_capture_sessions_expires_at", "appeal_capture_sessions", ["expires_at"])
    op.create_table(
        "appeal_rate_limits",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
    )


def downgrade():
    raise RuntimeError("Restore a backup; downgrading would delete citizens' appeals and photos.")
