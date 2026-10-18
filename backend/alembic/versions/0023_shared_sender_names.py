"""Share sender names across chats without losing existing per-chat signatures."""

import sqlalchemy as sa

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "max_senders",
        sa.Column("sender_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sender_id > 0", name="ck_max_sender_id"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 150", name="ck_max_sender_name"),
    )
    # Use the most recently edited name if a sender has different names in multiple
    # chats. Ties are deterministic. Keep every original row for recovery/history.
    op.execute("""
        INSERT INTO max_senders (sender_id, name, created_at, updated_at)
        SELECT sender_id, name, first_registered_at, updated_at FROM (
            SELECT sender_id, name, updated_at,
                   MIN(created_at) OVER (PARTITION BY sender_id) AS first_registered_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY sender_id ORDER BY updated_at DESC, created_at DESC, chat_id ASC
                   ) AS position
            FROM chat_senders
        ) names WHERE position = 1
    """)


def downgrade():
    raise RuntimeError("Shared sender names must be preserved. Restore a pre-migration backup to roll back.")
