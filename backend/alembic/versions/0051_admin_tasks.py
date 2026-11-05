"""Identify and deduplicate internal tasks assigned by administrators."""

import sqlalchemy as sa

from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("citizen_appeals", sa.Column("admin_submission_id", sa.String(36), nullable=True))
    op.create_unique_constraint("uq_admin_task_submission", "citizen_appeals",
                                ["organization_id", "admin_submission_id"])


def downgrade():
    op.drop_constraint("uq_admin_task_submission", "citizen_appeals", type_="unique")
    op.drop_column("citizen_appeals", "admin_submission_id")
