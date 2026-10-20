"""Keep explicit human day confirmations without modifying photos or model labels."""

import sqlalchemy as sa

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "day_closures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("photo_count", sa.Integer(), nullable=False),
    )
    op.create_index("ix_day_closures_day", "day_closures", ["day"])
    op.create_table(
        "day_photo_reviews",
        sa.Column("photo_id", sa.Integer(), sa.ForeignKey("photos.id"), primary_key=True),
        sa.Column("closure_id", sa.Integer(), sa.ForeignKey("day_closures.id"), nullable=False),
        sa.Column("photo_date", sa.Date(), nullable=False),
        sa.Column("sha256", sa.String(64)),
        sa.Column("photo_time", sa.Time()),
        sa.Column("latitude", sa.Float()),
        sa.Column("longitude", sa.Float()),
        sa.Column("district_id", sa.Integer()),
        sa.Column("work_type", sa.String(60)),
        sa.Column("is_defect", sa.Boolean(), nullable=False),
        sa.Column("cohort", sa.String(20), nullable=False),
    )
    op.create_index("ix_day_photo_reviews_closure_id", "day_photo_reviews", ["closure_id"])
    op.create_index("ix_day_photo_reviews_photo_date", "day_photo_reviews", ["photo_date"])


def downgrade():
    raise RuntimeError("Day confirmations must be preserved. Restore a pre-migration backup to roll back.")
