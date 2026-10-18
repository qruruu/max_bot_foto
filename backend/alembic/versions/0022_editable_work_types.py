"""Move the existing work catalog to durable storage; fresh installations start empty."""

import sqlalchemy as sa

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

# Frozen legacy output-head order. Never import a mutable application catalog here.
LEGACY = (
    ("DEICING_MANUAL", "ПГМ"), ("SNOW_MANUAL", "ПОДХОДЫ"), ("BIN_EMPTYING", "УРНЫ"),
    ("LAWN_LITTER", "МУСОР_ГАЗОН"), ("DRAIN_CLEANING", "КОЛОДЦЫ"), ("METAL_CUTTING", "АРМАТУРА"),
    ("PLAYGROUND_MAINTENANCE", "ПЛОЩАДКИ"), ("UNPAVED_LITTER", "СЛУЧ_МУСОР"),
    ("SWEEPING", "ПОДМЕТАНИЕ"), ("BIN_WASHING", "МОЙКА_УРН"), ("LAWN_RAKING", "ГРАБЛИ"),
    ("GREEN_CLEANING", "ГАЗОН"), ("GRASS_MOWING", "ПОКОС"), ("PAVING_WASHING", "БРУСЧ_МОЙКА"),
    ("SNOW_MECHANICAL", "МЕХ_СНЕГ"), ("SNOW_REMOVAL", "ВЫВОЗ_СНЕГА"),
)
PRIORITY = ("BIN_EMPTYING", "PLAYGROUND_MAINTENANCE", "SNOW_MANUAL", "DEICING_MANUAL", "GREEN_CLEANING")
DISPLAY = PRIORITY + tuple(code for code, _ in LEGACY if code not in PRIORITY)


def upgrade():
    conn = op.get_bind()
    # Migration precedes the first admin setup on a fresh server. An existing installation
    # can have no photos yet, so users/chats/model history are also evidence of prior use.
    existing = any(conn.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None
                   for table in ("users", "chats", "photos", "model_versions"))
    table = op.create_table(
        "work_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(60), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("filename_label", sa.String(100), nullable=False),
        sa.Column("model_index", sa.Integer(), nullable=False, unique=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("model_index >= 0 AND sort_order >= 1 AND version >= 1"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 100"),
    )
    op.create_index("ix_work_types_name_unique", "work_types", [sa.text("lower(name)")], unique=True)
    if existing:
        op.bulk_insert(table, [
            {"code": code, "name": name, "filename_label": name,
             "model_index": index, "sort_order": DISPLAY.index(code) + 1}
            for index, (code, name) in enumerate(LEGACY)
        ])
    # Intentionally no UPDATE of photos, chat rules, models, weights or training snapshots.


def downgrade():
    raise RuntimeError("The user work catalog must be preserved. Restore a pre-migration backup to roll back.")
