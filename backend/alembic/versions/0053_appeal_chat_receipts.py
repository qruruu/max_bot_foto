"""Track when an appeal chat message has been read by another participant."""

import sqlalchemy as sa

from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("appeal_events", sa.Column("read_at", sa.DateTime(timezone=True)))


def downgrade():
    op.drop_column("appeal_events", "read_at")
