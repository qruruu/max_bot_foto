"""Inspection chat photo attachments and private message forwarding."""

import sqlalchemy as sa

from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("inspection_messages", sa.Column("photo_organization_id", sa.String(36),
                  sa.ForeignKey("organizations.id", name="fk_inspection_message_photo_org")))
    op.add_column("inspection_messages", sa.Column("photo_id", sa.Integer()))
    op.add_column("inspection_messages", sa.Column("forwarded_from_id", sa.Integer(),
                  sa.ForeignKey("inspection_messages.id", name="fk_inspection_message_forward")))
    op.drop_constraint("inspection_messages_check", "inspection_messages", type_="check")
    op.create_check_constraint("ck_inspection_message_content", "inspection_messages",
        "sender_key <> recipient_key AND length(trim(body)) BETWEEN 0 AND 4000 "
        "AND (length(trim(body)) > 0 OR photo_id IS NOT NULL) "
        "AND ((photo_id IS NULL AND photo_organization_id IS NULL) "
        "OR (photo_id IS NOT NULL AND photo_id > 0 AND photo_organization_id IS NOT NULL))")


def downgrade():
    op.execute("UPDATE inspection_messages SET body = 'Фотография #' || photo_id WHERE length(trim(body)) = 0")
    op.drop_constraint("ck_inspection_message_content", "inspection_messages", type_="check")
    op.create_check_constraint("inspection_messages_check", "inspection_messages",
                               "sender_key <> recipient_key AND length(trim(body)) BETWEEN 1 AND 4000")
    for name in ("forwarded_from_id", "photo_id", "photo_organization_id"):
        op.drop_column("inspection_messages", name)
