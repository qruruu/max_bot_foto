"""Persist company folder names and previous roots without moving existing originals."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table(
        "disk_folder_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("folder_sets", postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
                  nullable=False, server_default=sa.text("'[]'")),
        sa.CheckConstraint("id=1"),
    )
    op.bulk_insert(table, [{"id": 1, "version": 1, "folder_sets": []}])


def downgrade():
    raise RuntimeError("Company folder history must be preserved. Restore a pre-migration backup to roll back.")
