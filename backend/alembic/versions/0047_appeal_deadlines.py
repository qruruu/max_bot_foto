"""Internal assignment deadlines and an immutable task finish timestamp."""

import sqlalchemy as sa

from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("appeal_tasks", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column("appeal_tasks", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    # No fabricated historical finish times: older tasks remain unknown.


def downgrade():
    op.drop_column("appeal_tasks", "finished_at")
    op.drop_column("appeal_tasks", "due_date")
