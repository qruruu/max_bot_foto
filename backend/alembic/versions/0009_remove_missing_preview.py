"""Remove only orphan previews; retain source history and allow a fresh file submission."""

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("photos", sa.Column("preview_removed_at", sa.DateTime(timezone=True)))
    op.drop_constraint("uq_photos_cohort_sha256", "photos", type_="unique")
    op.create_index(
        "uq_photos_active_cohort_sha256",
        "photos",
        ["cohort", "sha256"],
        unique=True,
        postgresql_where=sa.text("preview_removed_at IS NULL"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM photos WHERE preview_removed_at IS NOT NULL")):
        raise RuntimeError("Restore a backup to preserve removed-preview history and repeated submissions")
    op.drop_index("uq_photos_active_cohort_sha256", table_name="photos")
    op.create_unique_constraint("uq_photos_cohort_sha256", "photos", ["cohort", "sha256"])
    op.drop_column("photos", "preview_removed_at")
