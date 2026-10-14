"""Regenerate the documented v1 contract and strictly synthetic examples; no DB/network."""

import hashlib
import json
from datetime import date, datetime, time
from pathlib import Path

from app.catalog import WORK_TYPES, Status
from app.exchange import Dictionary, Index, Partition, PartitionRef, PhotoRecord, json_bytes


def generate(root: Path):
    schemas, samples = root / "schemas", root / "examples"
    schemas.mkdir(parents=True, exist_ok=True)
    samples.mkdir(parents=True, exist_ok=True)
    for model, name in [
        (PhotoRecord, "photo"),
        (Partition, "partition"),
        (Index, "index"),
        (Dictionary, "dictionary"),
    ]:
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        (schemas / f"{name}.schema.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")
    instant = datetime.fromisoformat("2026-10-13T10:00:00+05:00")
    base = PhotoRecord(
        source_photo_id="101",
        source_version=1,
        received_at=instant,
        updated_at=instant,
        photo_date=date(2026, 10, 12),
        photo_time=time(9, 24, 37),
        max_chat_id="-100000000001",
        max_message_id="synthetic-message-101",
        district_id="12",
        district_name="Пример микрорайона",
        source_work_type_code="BIN_EMPTYING",
        classification_mode="AI",
        work_rule_version=1,
        fixed_work_type_snapshot=None,
        work_type_source="AI",
        classification_confidence=0.93,
        status="ACCEPTED",
        review_reason=None,
        storage_status="SYNCED",
        duplicate_of=None,
        sha256="a" * 64,
        original_disk_path="disk:/MAX_PHOTOS/2026-10-12/Пример/Пример_УРНЫ_101.jpg",
        cohort="production",
        error_code=None,
        latitude=61.084,
        longitude=72.631,
    )
    scenarios = [
        ("01-ordinary", {}),
        (
            "02-fixed-chat",
            dict(
                source_photo_id="102",
                classification_mode="CHAT_FIXED",
                work_rule_version=2,
                fixed_work_type_snapshot="SNOW_MECHANICAL",
                source_work_type_code="SNOW_MECHANICAL",
                work_type_source="CHAT_FIXED",
                classification_confidence=None,
            ),
        ),
        (
            "03-unresolved",
            dict(
                source_photo_id="103",
                photo_date=None,
                photo_time=None,
                district_id=None,
                district_name=None,
                latitude=None,
                longitude=None,
                source_work_type_code=None,
                work_type_source=None,
                classification_confidence=None,
                status="NEEDS_REVIEW",
                review_reason=["DATE_MISSING", "COORDINATES_MISSING", "WORK_UNCERTAIN"],
                original_disk_path="disk:/MAX_PHOTOS/ДАТА_НЕ_ОПРЕДЕЛЕНА/МР_НЕ_ОПРЕДЕЛЕН/НЕ_ОПРЕДЕЛЕНО_103.jpg",
            ),
        ),
        (
            "04-duplicate",
            dict(
                source_photo_id="104",
                status="DUPLICATE",
                duplicate_of="101",
                sha256=None,
                original_disk_path=None,
                storage_status="NOT_REQUIRED",
                source_work_type_code=None,
                work_type_source=None,
                classification_confidence=None,
                photo_date=None,
                photo_time=None,
                district_id=None,
                district_name=None,
                latitude=None,
                longitude=None,
            ),
        ),
        (
            "05-pending",
            dict(
                source_photo_id="105",
                status="RECEIVED",
                storage_status="PENDING",
                sha256=None,
                original_disk_path=None,
                source_work_type_code=None,
                work_type_source=None,
                classification_confidence=None,
                photo_date=None,
                photo_time=None,
                district_id=None,
                district_name=None,
                latitude=None,
                longitude=None,
            ),
        ),
        (
            "06-error",
            dict(
                source_photo_id="106",
                status="ERROR",
                storage_status="ERROR",
                original_disk_path=None,
                error_code="HTTP_503",
            ),
        ),
        (
            "07-spam",
            dict(
                source_photo_id="107",
                status="SPAM",
                source_work_type_code=None,
                work_type_source="OPERATOR",
                original_disk_path="disk:/MAX_PHOTOS_SPAM/production/2026-10-12/Пример/Спам_107.jpg",
            ),
        ),
        (
            "08-corrected-ordinary",
            dict(
                source_version=2,
                updated_at=datetime.fromisoformat("2026-10-14T09:00:00+05:00"),
                photo_date=date(2026, 10, 11),
                source_work_type_code="SWEEPING",
                work_type_source="OPERATOR",
                storage_status="PENDING",
            ),
        ),
        ("09-late-photo", dict(source_photo_id="109", photo_date=date(2026, 10, 10))),
        (
            "10-test-cohort",
            dict(
                source_photo_id="110",
                cohort="training",
                original_disk_path="disk:/MAX_PHOTOS_TRAINING/2026-10-12/Пример/Пример_УРНЫ_110.jpg",
            ),
        ),
    ]
    for name, changes in scenarios:
        item = PhotoRecord.model_validate({**base.model_dump(), **changes})
        identity = "00000000-0000-4000-8000-000000000000-" + ("test" if item.cohort == "training" else item.cohort)
        as_of = max(instant, item.updated_at)
        part = Partition(
            source_instance_id=identity,
            cohort=item.cohort,
            source_timezone="Asia/Yekaterinburg",
            partition_received_date=date(2026, 10, 13),
            generation_id="00000000000000000001",
            produced_at=as_of,
            as_of=as_of,
            photo_count=1,
            items=[item],
        )
        (samples / f"{name}.json").write_bytes(json_bytes(part.model_dump(mode="json")))
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [[[[72.60, 61.08], [72.64, 61.08], [72.64, 61.10], [72.60, 61.10], [72.60, 61.08]]]],
    }
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "12",
                "properties": {
                    "source_district_id": "12",
                    "name": "Пример микрорайона",
                    "active": True,
                    "geometry_sha256": hashlib.sha256(json_bytes(geometry)).hexdigest(),
                },
                "geometry": geometry,
            }
        ],
    }
    (samples / "districts.geojson").write_bytes(json_bytes(geojson))
    dictionary = Dictionary(
        source_instance_id="00000000-0000-4000-8000-000000000000-production",
        cohort="production",
        work_types=[{"code": c, "name": n[0]} for c, n in WORK_TYPES.items()],
        statuses=list(Status),
        storage_statuses=["PENDING", "ERROR", "SYNCED", "NOT_REQUIRED"],
        districts_geojson=geojson,
    )
    (samples / "dictionary.json").write_bytes(json_bytes(dictionary.model_dump(mode="json")))
    index = Index(
        source_instance_id=dictionary.source_instance_id,
        cohort="production",
        source_timezone="Asia/Yekaterinburg",
        published_at=instant,
        as_of=instant,
        index_generation_id="00000000000000000001",
        photo_count=1,
        partitions=[
            PartitionRef(
                file_ref="01-ordinary.json",
                sha256=hashlib.sha256((samples / "01-ordinary.json").read_bytes()).hexdigest(),
                received_date=date(2026, 10, 13),
                generation_id="00000000000000000001",
                photo_count=1,
            )
        ],
        dictionaries={
            "file_ref": "dictionary.json",
            "sha256": hashlib.sha256((samples / "dictionary.json").read_bytes()).hexdigest(),
        },
    )
    (samples / "index.json").write_bytes(json_bytes(index.model_dump(mode="json")))


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[2] / "docs/exchange")
