"""Allow logins to be reused after deleting an inspector."""

import sqlalchemy as sa

from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("inspectors_login_key", "inspectors", type_="unique")
    op.create_index("uq_inspectors_live_login", "inspectors", ["login"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL"))


def downgrade():
    op.execute("UPDATE inspectors SET login = '!deleted:' || id WHERE deleted_at IS NOT NULL")
    op.create_unique_constraint("inspectors_login_key", "inspectors", ["login"])
    op.drop_index("uq_inspectors_live_login", table_name="inspectors")
