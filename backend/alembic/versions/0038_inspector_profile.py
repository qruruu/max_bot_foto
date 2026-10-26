"""Inspector personal settings and independently revocable device sessions."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("inspectors", sa.Column("avatar_image", sa.LargeBinary()))
    op.add_column("inspectors", sa.Column("sidebar_order", postgresql.JSONB(), nullable=False, server_default="[]"))
    op.add_column("inspection_sessions", sa.Column("id", sa.String(36), nullable=False,
                                                  server_default=sa.text("gen_random_uuid()::text")))
    op.create_unique_constraint("uq_inspection_sessions_id", "inspection_sessions", ["id"])
    op.add_column("inspection_sessions", sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                                                  server_default=sa.func.now()))
    op.add_column("inspection_sessions", sa.Column("last_seen_at", sa.DateTime(timezone=True)))
    op.add_column("inspection_sessions", sa.Column("user_agent", sa.String(512)))
    op.add_column("inspection_sessions", sa.Column("ip_address", sa.String(45)))


def downgrade():
    for key in ("ip_address", "user_agent", "last_seen_at", "created_at", "id"):
        op.drop_column("inspection_sessions", key)
    op.drop_column("inspectors", "sidebar_order")
    op.drop_column("inspectors", "avatar_image")
