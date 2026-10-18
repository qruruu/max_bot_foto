"""Persist an operator's defect marker independently of the work category."""

import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("photos", sa.Column("is_defect", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade():
    op.drop_column("photos", "is_defect")
