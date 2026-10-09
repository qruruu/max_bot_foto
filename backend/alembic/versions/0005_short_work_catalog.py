"""Adopt 16 short work labels and enqueue district-folder relocation of existing files."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# Frozen migration: retain the original decision in audit/raw AI history.
MERGED_CODES = {
    "MAF_INSPECTION": "PLAYGROUND_MAINTENANCE",
    "PLAYGROUND_SNOW": "PLAYGROUND_MAINTENANCE",
    "PLAYGROUND_SUMMER": "PLAYGROUND_MAINTENANCE",
    "PLAYGROUND_MOWING": "PLAYGROUND_MAINTENANCE",
    "FALLEN_TREE": "GREEN_CLEANING",
    "CUT_GRASS_REMOVAL": "GRASS_MOWING",
}
ARCHITECTURE = "resnet18-local-v2-short16"


def upgrade():
    conn = op.get_bind()
    audit = sa.text("""
        INSERT INTO audit_logs (action, object_type, object_id, photo_id, old_value, new_value)
        VALUES (:action, :object_type, :id, :photo_id, :old, :new)
    """).bindparams(sa.bindparam("old", type_=JSONB), sa.bindparam("new", type_=JSONB))
    update_photo = sa.text("""
        UPDATE photos SET work_type=:work, ai_alternatives=:alternatives, version=version+1,
            storage_status=CASE WHEN :relocate THEN 'PENDING' ELSE storage_status END,
            updated_at=now()
        WHERE id=:id
    """).bindparams(sa.bindparam("alternatives", type_=JSONB))
    last_id = 0
    while True:
        rows = conn.execute(sa.text("""
            SELECT id, work_type, ai_alternatives, analyzed_at, sha256, status, yandex_disk_path
            FROM photos WHERE id > :last_id ORDER BY id LIMIT 500
        """), {"last_id": last_id}).mappings().all()
        if not rows:
            break
        for row in rows:
            work = MERGED_CODES.get(row["work_type"], row["work_type"])
            alternatives = list(dict.fromkeys(
                MERGED_CODES.get(code, code) for code in row["ai_alternatives"] or []
            ))
            relocate = bool(
                row["yandex_disk_path"] and row["analyzed_at"] and row["sha256"]
                and row["status"] in {"ACCEPTED", "NEEDS_REVIEW", "ERROR", "SPAM"}
            )
            if work == row["work_type"] and alternatives == row["ai_alternatives"] and not relocate:
                continue
            conn.execute(update_photo, {
                "id": row["id"], "work": work, "alternatives": alternatives, "relocate": relocate,
            })
            conn.execute(audit, {
                "action": "WORK_CATALOG_UPDATED", "object_type": "photo",
                "id": row["id"], "photo_id": row["id"],
                "old": {"work_type": row["work_type"], "ai_alternatives": row["ai_alternatives"],
                        "yandex_disk_path": row["yandex_disk_path"]},
                "new": {"work_type": work, "ai_alternatives": alternatives,
                        "catalog": "short16", "relocation_queued": relocate},
            })
            if relocate:
                # Keep the old path until the normal worker confirms the move and remote hash.
                conn.execute(sa.text("""
                    INSERT INTO jobs (kind, object_id, dedupe_key, status, attempts)
                    VALUES ('SYNC', :id, :key, 'PENDING', 0)
                    ON CONFLICT (dedupe_key) DO NOTHING
                """), {"id": row["id"], "key": f"catalog-short16:{row['id']}"})
        last_id = rows[-1]["id"]

    old_models = conn.execute(sa.text("""
        SELECT id, status FROM model_versions
        WHERE status IN ('ACTIVE', 'TRAINING')
          AND (metrics->>'architecture') IS DISTINCT FROM :architecture
    """), {"architecture": ARCHITECTURE}).mappings().all()
    for model in old_models:
        status = "SUPERSEDED" if model["status"] == "ACTIVE" else "INTERRUPTED"
        conn.execute(sa.text("""
            UPDATE model_versions SET status=:status, finished_at=COALESCE(finished_at, now())
            WHERE id=:id
        """), {"id": model["id"], "status": status})
        conn.execute(audit, {
            "action": "MODEL_CATALOG_CHANGED", "object_type": "model", "id": model["id"],
            "photo_id": None, "old": {"status": model["status"]},
            "new": {"status": status, "reason": "short16_requires_retraining"},
        })


def downgrade():
    raise RuntimeError(
        "Merged work categories cannot be split automatically. Restore a pre-migration backup to roll back."
    )
