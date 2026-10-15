"""Remember IDs of incoming MAX chats before an administrator enables photo intake."""

import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "discovered_chats",
        sa.Column("max_chat_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("message_preview", sa.String(200)),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("discovered_chats")
