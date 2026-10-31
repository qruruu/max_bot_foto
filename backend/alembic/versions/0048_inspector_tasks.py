"""Inspector task deadlines, children and private files."""
import sqlalchemy as sa

from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("appeal_photos", "latitude", existing_type=sa.Float(), nullable=True)
    op.alter_column("appeal_photos", "longitude", existing_type=sa.Float(), nullable=True)
    op.drop_constraint("appeal_events_visibility_check", "appeal_events", type_="check")
    op.create_check_constraint("appeal_events_visibility_check", "appeal_events", "visibility IN ('STAFF', 'ADMIN', 'TASK', 'INSPECTOR')")
    op.add_column("citizen_appeals", sa.Column("inspector_due_date", sa.Date()))
    op.add_column("citizen_appeals", sa.Column("parent_id", sa.Integer(), sa.ForeignKey("citizen_appeals.id")))
    op.create_index("ix_citizen_appeals_parent_id", "citizen_appeals", ["parent_id"])
    # The initial migration used PostgreSQL's generated name for this constraint.
    op.drop_constraint("citizen_appeals_photo_count_check", "citizen_appeals", type_="check")
    op.create_check_constraint("ck_appeal_photo_count", "citizen_appeals", "photo_count BETWEEN 0 AND 3")
    op.create_table("appeal_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("appeal_id", sa.Integer(), sa.ForeignKey("citizen_appeals.id"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("appeal_events.id")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False))
    op.create_index("ix_appeal_files_appeal_id", "appeal_files", ["appeal_id"])
    op.create_index("ix_appeal_files_event_id", "appeal_files", ["event_id"])


def downgrade():
    op.execute("UPDATE appeal_events SET visibility = 'STAFF' WHERE visibility = 'INSPECTOR'")
    op.drop_constraint("appeal_events_visibility_check", "appeal_events", type_="check")
    op.create_check_constraint("appeal_events_visibility_check", "appeal_events", "visibility IN ('STAFF', 'ADMIN', 'TASK')")
    op.drop_table("appeal_files")
    op.drop_constraint("ck_appeal_photo_count", "citizen_appeals", type_="check")
    # Keep zero-photo tasks valid when rolling back application code.
    op.create_check_constraint("citizen_appeals_photo_count_check", "citizen_appeals", "photo_count BETWEEN 0 AND 3")
    op.drop_index("ix_citizen_appeals_parent_id", "citizen_appeals")
    op.drop_column("citizen_appeals", "parent_id")
    op.drop_column("citizen_appeals", "inspector_due_date")
