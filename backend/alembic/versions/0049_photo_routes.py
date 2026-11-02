"""Independent photo route plans. No change to photo ingestion or existing territories."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "photo_route_plans",
        sa.Column("district_id", sa.Integer(), sa.ForeignKey("districts.id"), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("chat_ids", JSONB(), nullable=False),
        sa.Column("paths", JSONB(), nullable=False),
        sa.Column("buildings", JSONB(), nullable=False),
        sa.Column("buildings_source", sa.String(100), nullable=False),
        sa.Column("snap_m", sa.Integer(), nullable=False),
        sa.Column("max_gap_minutes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("photo_route_plans")
