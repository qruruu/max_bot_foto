"""Restrict operators to selected MAX chats without changing existing access."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("allowed_chat_ids", JSONB(none_as_null=True), nullable=True))
    op.create_check_constraint(
        "user_allowed_chats_array", "users",
        "allowed_chat_ids IS NULL OR jsonb_typeof(allowed_chat_ids)='array'",
    )


def downgrade():
    if op.get_bind().scalar(sa.text(
        "SELECT count(*) FROM users WHERE role='OPERATOR' AND allowed_chat_ids IS NOT NULL"
    )):
        raise RuntimeError("Remove chat restrictions explicitly before rolling back chat access checks")
    op.drop_constraint("user_allowed_chats_array", "users", type_="check")
    op.drop_column("users", "allowed_chat_ids")
