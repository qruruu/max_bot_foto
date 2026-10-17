"""Add private conversations between panel users."""

import sqlalchemy as sa

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "operator_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_id", sa.String(36), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("sender_id <> recipient_id", name="ck_operator_message_peer"),
        sa.CheckConstraint("length(body) BETWEEN 1 AND 4000", name="ck_operator_message_body"),
        sa.UniqueConstraint("sender_id", "client_id", name="uq_operator_message_client"),
    )
    op.create_index("ix_operator_messages_pair", "operator_messages", ["sender_id", "recipient_id", "id"])
    op.create_index("ix_operator_messages_unread", "operator_messages", ["recipient_id", "read_at", "sender_id"])


def downgrade():
    op.drop_index("ix_operator_messages_unread", "operator_messages")
    op.drop_index("ix_operator_messages_pair", "operator_messages")
    op.drop_table("operator_messages")
