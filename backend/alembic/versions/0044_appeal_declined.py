"""A final administrator refusal with a response and optional photos."""

import sqlalchemy as sa

from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade():
    for constraint in sa.inspect(op.get_bind()).get_check_constraints("citizen_appeals"):
        if "status" in constraint["sqltext"]:
            op.drop_constraint(constraint["name"], "citizen_appeals", type_="check")
    op.create_check_constraint("ck_citizen_appeals_status", "citizen_appeals",
        "status IN ('NEW','IN_REVIEW','ASSIGNED','IN_PROGRESS','COMPLETED','REJECTED','CANCELLED','RESOLVED','DECLINED','SPAM')")


def downgrade():
    raise RuntimeError("Restore a backup; removing refusal statuses would lose appeal decisions.")
