"""Index active photo coordinates for viewport reads."""

from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade():
    # Keep photo intake writable while indexing an existing archive.
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_photos_map_position")
        op.execute("""
            CREATE INDEX CONCURRENTLY ix_photos_map_position ON photos
            USING gist (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326))
            WHERE preview_removed_at IS NULL AND longitude IS NOT NULL AND latitude IS NOT NULL
        """)


def downgrade():
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_photos_map_position")
