"""Keep training history when obsolete model weights are removed."""

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "model_versions", sa.Column("weights_removed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade():
    op.drop_column("model_versions", "weights_removed_at")
