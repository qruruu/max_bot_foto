"""Map-based public appeals, address allowlists and organization tasks."""

import sqlalchemy as sa

from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade():
    # Retain the privacy promised by the earlier, private camera form.
    for column in (
        sa.Column("address_id", sa.String(36)), sa.Column("latitude", sa.Float()),
        sa.Column("longitude", sa.Float()), sa.Column("is_public", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("public_response", sa.Text(), nullable=False, server_default=""),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("citizen_appeals", column)
    connection = op.get_bind()
    constraints = sa.inspect(connection).get_check_constraints("citizen_appeals")
    for constraint in constraints:
        if "status" in constraint["sqltext"]:
            op.drop_constraint(constraint["name"], "citizen_appeals", type_="check")
    op.create_check_constraint("ck_citizen_appeal_status", "citizen_appeals",
        "status IN ('NEW','IN_REVIEW','ASSIGNED','IN_PROGRESS','COMPLETED','REJECTED','RESOLVED','SPAM')")
    op.create_table("appeal_addresses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("label", sa.String(300), nullable=False), sa.Column("district_id", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "label"))
    op.create_index("ix_appeal_addresses_organization_id", "appeal_addresses", ["organization_id"])
    op.create_table("appeal_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("appeal_id", sa.Integer(), sa.ForeignKey("citizen_appeals.id"), nullable=False),
        sa.Column("operator_id", sa.Integer(), nullable=False), sa.Column("operator_name", sa.String(150), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result_comment", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('ASSIGNED','IN_PROGRESS','COMPLETED','REJECTED')"))
    op.create_index("ix_appeal_tasks_appeal_id", "appeal_tasks", ["appeal_id"])
    op.create_table("appeal_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("appeal_id", sa.Integer(), sa.ForeignKey("citizen_appeals.id"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("appeal_tasks.id")),
        sa.Column("content", sa.LargeBinary(), nullable=False), sa.Column("preview", sa.LargeBinary(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False), sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_appeal_attachments_appeal_id", "appeal_attachments", ["appeal_id"])
    op.create_index("ix_appeal_attachments_task_id", "appeal_attachments", ["task_id"])
    op.create_index("ix_citizen_appeals_public_city", "citizen_appeals", ["city", "is_public", "id"])


def downgrade():
    raise RuntimeError("Restore a backup; removing the workflow would lose task results and public responses.")
