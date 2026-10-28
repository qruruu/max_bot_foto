"""Private inspector appeals share the organization workflow, never the city wall."""

import sqlalchemy as sa

from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("citizen_appeals", sa.Column("submitted_by_inspector_id", sa.Integer(), sa.ForeignKey("inspectors.id")))
    op.add_column("citizen_appeals", sa.Column("submitted_by_inspector_name", sa.String(150), nullable=False, server_default=""))
    op.add_column("citizen_appeals", sa.Column("inspector_submission_id", sa.String(36)))
    op.create_unique_constraint("uq_inspector_appeal_submission", "citizen_appeals",
                                ["submitted_by_inspector_id", "inspector_submission_id"])
    op.create_check_constraint("ck_inspector_appeal_private", "citizen_appeals",
                               "submitted_by_inspector_id IS NULL OR is_public = false")


def downgrade():
    raise RuntimeError("Restore a backup; removing inspector attribution would lose appeal origins.")
