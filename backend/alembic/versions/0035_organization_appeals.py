"""Route citizen appeals to registered organizations and their cities/work types."""

import sqlalchemy as sa

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade():
    # Existing organizations need an explicit city before appearing in the public form.
    op.add_column("organizations", sa.Column("city", sa.String(150)))
    op.add_column("citizen_appeals", sa.Column("organization_id", sa.String(36),
                                             sa.ForeignKey("organizations.id")))
    op.add_column("citizen_appeals", sa.Column("organization_name", sa.String(150),
                                             nullable=False, server_default=""))
    op.add_column("citizen_appeals", sa.Column("work_type_name", sa.String(100),
                                             nullable=False, server_default=""))
    op.alter_column("citizen_appeals", "category", type_=sa.String(60))
    op.create_index("ix_citizen_appeals_organization_id", "citizen_appeals", ["organization_id"])
    op.create_index("ix_citizen_appeals_org_status_id", "citizen_appeals", ["organization_id", "status", "id"])


def downgrade():
    raise RuntimeError("Restore a backup; removing appeal routing would lose the recipients.")
