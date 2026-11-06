"""Add screenshots, reply quotes and forwarding attribution to chats."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None

OPERATOR = "length(body) <= 4000 AND (length(body) > 0 OR photo_id IS NOT NULL)"
INSPECTION = (
    "sender_key <> recipient_key AND length(trim(body)) BETWEEN 0 AND 4000 "
    "AND (length(trim(body)) > 0 OR photo_id IS NOT NULL) "
    "AND ((photo_id IS NULL AND photo_organization_id IS NULL) "
    "OR (photo_id IS NOT NULL AND photo_id > 0 AND photo_organization_id IS NOT NULL))"
)
CONSTRAINTS = (
    ("operator_messages", "ck_operator_message_body", OPERATOR),
    ("inspection_messages", "ck_inspection_message_content", INSPECTION),
)


def upgrade():
    for table in ("operator_messages", "inspection_messages", "appeal_events"):
        op.add_column(table, sa.Column("forwarded_name", sa.String(150)))
        op.add_column(table, sa.Column("reply", JSONB()))
    op.add_column("operator_messages", sa.Column("forwarded_from_id", sa.Integer(),
                  sa.ForeignKey("operator_messages.id", name="fk_operator_message_forward")))
    for table, name, rule in CONSTRAINTS:
        for number in range(1, 4):
            op.add_column(table, sa.Column(f"screenshot_{number}", sa.LargeBinary()))
        op.add_column(table, sa.Column("screenshot_count", sa.Integer(), server_default="0", nullable=False))
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, rule.replace(
            "OR photo_id IS NOT NULL)", "OR photo_id IS NOT NULL OR screenshot_count > 0)"))


def downgrade():
    raise RuntimeError("Restore a backup to downgrade without losing chat messages and screenshots.")
