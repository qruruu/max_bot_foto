"""A resident's own short subject, separate from the assigned work type."""

import sqlalchemy as sa

from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("citizen_appeals", sa.Column("subject", sa.String(80), nullable=False, server_default=""))


def downgrade():
    op.drop_column("citizen_appeals", "subject")
