"""Attach a photo reference to a private operator message, preserving existing history."""

import sqlalchemy as sa

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("operator_messages", sa.Column("photo_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("operator_messages") as batch:
        batch.create_foreign_key("fk_operator_messages_photo", "photos", ["photo_id"], ["id"])
        batch.drop_constraint("ck_operator_message_body", type_="check")
        batch.create_check_constraint(
            "ck_operator_message_body", "length(body) <= 4000 AND (length(body) > 0 OR photo_id IS NOT NULL)",
        )


def downgrade():
    raise RuntimeError("Forwarded photo messages must be preserved. Restore a pre-migration backup to roll back.")
