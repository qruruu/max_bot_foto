"""Record task shares and explicit photo shares in operator chats."""

import sqlalchemy as sa

from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "inspector_appeal_shares",
        sa.Column("inspector_id", sa.Integer(), sa.ForeignKey("inspectors.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("appeal_id", sa.Integer(), sa.ForeignKey("citizen_appeals.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_inspector_appeal_shares_appeal_id", "inspector_appeal_shares", ["appeal_id"])
    op.add_column("operator_messages", sa.Column("photo_shared", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("operator_messages", "photo_shared")
    op.drop_table("inspector_appeal_shares")
