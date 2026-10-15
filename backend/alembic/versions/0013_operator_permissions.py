"""Allow administrators to restrict or delegate functions for operator accounts."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

LEGACY_PERMISSIONS = '["reports_view","photos_view","originals_view","photos_edit","spam_view","reports_export","previews_remove","districts_view"]'


def upgrade():
    op.add_column(
        "users",
        sa.Column(
            "permissions", JSONB(), nullable=False, server_default=sa.text(f"'{LEGACY_PERMISSIONS}'::jsonb")
        ),
    )
    op.create_check_constraint("user_permissions_array", "users", "jsonb_typeof(permissions)='array'")


def downgrade():
    # Restoring old code would give restricted operators the full legacy set again.
    if op.get_bind().scalar(
        sa.text("""SELECT count(*) FROM users
        WHERE role='OPERATOR' AND permissions <> CAST(:legacy AS jsonb)""").bindparams(
            legacy=LEGACY_PERMISSIONS
        )
    ):
        raise RuntimeError("Restricted operators require permission checks; restore a backup to roll back")
    op.drop_constraint("user_permissions_array", "users", type_="check")
    op.drop_column("users", "permissions")
