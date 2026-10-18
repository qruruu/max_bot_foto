"""Store per-chat labels for MAX photo senders."""

import sqlalchemy as sa

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_senders",
        sa.Column("chat_id", sa.Integer(), sa.ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("sender_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sender_id > 0", name="ck_chat_sender_id"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 150", name="ck_chat_sender_name"),
    )


def downgrade():
    op.drop_table("chat_senders")
