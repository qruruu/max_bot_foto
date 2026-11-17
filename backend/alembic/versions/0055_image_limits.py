"""Allow up to ten images per appeal or chat message."""

import sqlalchemy as sa

from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None

CHAT_TABLES = ("operator_messages", "inspection_messages")


def upgrade():
    op.drop_constraint("ck_appeal_photo_count", "citizen_appeals", type_="check")
    op.create_check_constraint("ck_appeal_photo_count", "citizen_appeals", "photo_count BETWEEN 0 AND 10")
    for table in CHAT_TABLES:
        for number in range(4, 11):
            op.add_column(table, sa.Column(f"screenshot_{number}", sa.LargeBinary()))


def downgrade():
    raise RuntimeError("Restore a backup to downgrade without losing photos and screenshots.")
