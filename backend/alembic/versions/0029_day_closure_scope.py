"""Remember the complete closing scope, including chats with no photos yet."""

import sqlalchemy as sa

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("day_closures", sa.Column("cohort", sa.String(20)))
    op.add_column("day_closures", sa.Column("all_chats", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "day_closure_chats",
        sa.Column("closure_id", sa.Integer(), sa.ForeignKey("day_closures.id"), primary_key=True),
        sa.Column("max_chat_id", sa.BigInteger(), primary_key=True),
    )


def downgrade():
    raise RuntimeError("Day closing scopes must be preserved. Restore a pre-migration backup to roll back.")
