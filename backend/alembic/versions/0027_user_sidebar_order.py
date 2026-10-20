"""Persist personal sidebar order without changing account access."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("sidebar_order", postgresql.JSONB(),
                                    nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.create_check_constraint("user_sidebar_order_array", "users", "jsonb_typeof(sidebar_order)='array'")


def downgrade():
    op.drop_constraint("user_sidebar_order_array", "users", type_="check")
    op.drop_column("users", "sidebar_order")
