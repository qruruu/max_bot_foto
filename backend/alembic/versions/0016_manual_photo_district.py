"""Keep an operator's district choice independently of photo coordinates."""

import sqlalchemy as sa

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("photos", sa.Column("district_source", sa.String(20), nullable=True))
    op.execute("UPDATE photos SET district_source = 'COORDINATES' WHERE district_id IS NOT NULL")
    op.create_check_constraint(
        "ck_photos_district_source",
        "photos",
        "district_source IS NULL OR district_source IN ('COORDINATES','OPERATOR')",
    )
    op.create_check_constraint(
        "ck_photos_manual_district",
        "photos",
        "district_source IS DISTINCT FROM 'OPERATOR' OR district_id IS NOT NULL",
    )


def downgrade():
    op.drop_constraint("ck_photos_manual_district", "photos", type_="check")
    op.drop_constraint("ck_photos_district_source", "photos", type_="check")
    op.drop_column("photos", "district_source")
