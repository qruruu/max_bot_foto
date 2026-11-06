"""Keep audit references to deleted accounts."""

import sqlalchemy as sa

from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("users", "inspectors"):
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(timezone=True)))


def downgrade():
    for table in ("inspectors", "users"):
        op.drop_column(table, "deleted_at")
