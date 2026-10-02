"""Local supervised model registry and immutable training snapshots."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("dataset_fingerprint", sa.String(64), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("labels_snapshot", JSONB, nullable=False),
        sa.Column("metrics", JSONB, nullable=False),
        sa.Column("supported_classes", JSONB, nullable=False),
        sa.Column("model_path", sa.Text()),
        sa.Column("model_sha256", sa.String(64)),
        sa.Column("last_error", sa.Text()),
    )
    op.create_index("ix_model_versions_status", "model_versions", ["status"])
    op.create_index("ix_model_versions_dataset_fingerprint", "model_versions", ["dataset_fingerprint"])
    op.create_index(
        "ix_one_active_model",
        "model_versions",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade():
    op.drop_table("model_versions")
