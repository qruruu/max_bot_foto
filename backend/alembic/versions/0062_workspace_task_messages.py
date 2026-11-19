"""Attach task cards to organization chats."""

import sqlalchemy as sa

from alembic import op

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("operator_messages", sa.Column("shared_appeal_id", sa.Integer()))
    op.create_index("ix_operator_shared_appeal", "operator_messages", ["recipient_id", "shared_appeal_id"],
                    postgresql_where=sa.text("shared_appeal_id IS NOT NULL"))


def downgrade():
    op.drop_index("ix_operator_shared_appeal", table_name="operator_messages")
    op.drop_column("operator_messages", "shared_appeal_id")
