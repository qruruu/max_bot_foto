"""Add optional work-type guidance without changing codes, model indices or photo links."""

import sqlalchemy as sa

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("work_types", sa.Column("description", sa.Text(), nullable=False, server_default=""))


def downgrade():
    raise RuntimeError("Work-type descriptions must be preserved. Restore a pre-migration backup to roll back.")
