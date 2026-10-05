"""Reversible operator spam archive, independent of storage/retry state."""

import re

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

OLD_STATUSES = "'RECEIVED','PROCESSING','ACCEPTED','NEEDS_REVIEW','REJECTED','DUPLICATE','FORWARDED','ERROR'"


def upgrade():
    checks = sa.inspect(op.get_bind()).get_check_constraints("photos")
    status_checks = [c for c in checks if re.search(r"\bstatus\b", c["sqltext"])]
    if len(status_checks) != 1:
        raise RuntimeError("Expected exactly one photo status constraint")
    op.drop_constraint(status_checks[0]["name"], "photos", type_="check")
    op.add_column("photos", sa.Column("is_spam", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_check_constraint("ck_photos_status", "photos", f"status IN ({OLD_STATUSES},'SPAM')")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM photos WHERE is_spam OR status='SPAM'")):
        raise RuntimeError("Restore spam photos through the panel before downgrading")
    op.drop_constraint("ck_photos_status", "photos", type_="check")
    op.create_check_constraint("ck_photos_status", "photos", f"status IN ({OLD_STATUSES})")
    op.drop_column("photos", "is_spam")
