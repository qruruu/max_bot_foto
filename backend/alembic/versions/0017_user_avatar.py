"""Store a normalized profile avatar for each user."""

import sqlalchemy as sa

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("avatar_image", sa.LargeBinary(), nullable=True))


def downgrade():
    op.drop_column("users", "avatar_image")
