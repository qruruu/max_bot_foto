"""Attach shared tasks and photos to inspection chat messages."""

import sqlalchemy as sa

from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("inspection_messages", sa.Column("shared_appeal_id", sa.Integer()))
    op.create_foreign_key("fk_inspection_message_shared_appeal", "inspection_messages", "citizen_appeals",
                          ["shared_appeal_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_inspection_task_chat_recipient", "inspection_messages", ["recipient_key", "sender_key"],
                    postgresql_where=sa.text("shared_appeal_id IS NOT NULL"))
    op.add_column("inspection_messages", sa.Column("photo_shared", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("inspection_messages", "photo_shared")
    op.drop_index("ix_inspection_task_chat_recipient", table_name="inspection_messages")
    op.drop_constraint("fk_inspection_message_shared_appeal", "inspection_messages", type_="foreignkey")
    op.drop_column("inspection_messages", "shared_appeal_id")
