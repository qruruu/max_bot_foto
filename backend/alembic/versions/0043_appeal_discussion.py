"""Private appeal discussions, event history and a reversible archive."""

import sqlalchemy as sa

from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("citizen_appeals", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.create_index("ix_citizen_appeals_archived_at", "citizen_appeals", ["archived_at"])
    for table, statuses in (
        ("citizen_appeals", "'NEW','IN_REVIEW','ASSIGNED','IN_PROGRESS','COMPLETED','REJECTED','CANCELLED','RESOLVED','SPAM'"),
        ("appeal_tasks", "'ASSIGNED','IN_PROGRESS','COMPLETED','REJECTED','CANCELLED'"),
    ):
        for constraint in sa.inspect(op.get_bind()).get_check_constraints(table):
            if "status" in constraint["sqltext"]:
                op.drop_constraint(constraint["name"], table, type_="check")
        op.create_check_constraint("ck_" + table + "_status", table, f"status IN ({statuses})")
    op.create_table("appeal_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("appeal_id", sa.Integer(), sa.ForeignKey("citizen_appeals.id"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("actor_type", sa.String(30), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("actor_name", sa.String(150), nullable=False),
        sa.Column("actor_role", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20)), sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("visibility", sa.String(20), nullable=False), sa.Column("operator_id", sa.Integer()),
        sa.Column("client_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("visibility IN ('STAFF','ADMIN','TASK')"),
        sa.UniqueConstraint("appeal_id", "actor_type", "actor_id", "client_id", name="uq_appeal_event_client"))
    op.create_index("ix_appeal_events_appeal_id", "appeal_events", ["appeal_id"])
    op.create_index("ix_appeal_events_order", "appeal_events", ["appeal_id", "id"])
    # Preserve the known state without inventing transitions from before history existed.
    op.execute("""INSERT INTO appeal_events
        (appeal_id,kind,actor_type,actor_id,actor_name,actor_role,status,comment,visibility,created_at)
        SELECT id,'IMPORTED','SYSTEM','','Система','',status,
          'Состояние обращения на момент включения истории событий','STAFF',updated_at
        FROM citizen_appeals""")


def downgrade():
    raise RuntimeError("Restore a backup; removing discussion history would lose messages.")
