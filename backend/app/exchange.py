"""Manual durable snapshots. Immutable files are uploaded before their immutable index."""

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.catalog import Status
from app.config import settings
from app.db import engine
from app.domain import enqueue, now
from app.exchange_files import checked_files, content_hash, register_existing, register_manifest
from app.integrations import YandexDisk
from app.models import District, ExchangeFile, ExchangeState, Job, Photo, Publication
from app.processing import error_code
from app.schemas import WorkCode
from app.work_types import work_catalog

Cohort = Literal["training", "production"]


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PhotoRecord(Document):
    source_photo_id: str
    source_version: int = Field(ge=1)
    received_at: datetime
    updated_at: datetime
    photo_date: date | None
    photo_time: time | None
    max_chat_id: str
    max_message_id: str
    district_id: str | None
    district_name: str | None
    district_geometry_version: str | None = None
    source_work_type_code: WorkCode | None
    classification_mode: Literal["AI", "CHAT_FIXED", "LEGACY_UNKNOWN", "REVIEW"]
    work_rule_version: int | None
    fixed_work_type_snapshot: WorkCode | None
    work_type_source: Literal["AI", "OPERATOR", "CHAT_FIXED"] | None
    classification_confidence: float | None = Field(ge=0, le=1)
    status: Status
    review_reason: list[str] | None
    storage_status: Literal["PENDING", "ERROR", "SYNCED", "NOT_REQUIRED"]
    duplicate_of: str | None
    sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    original_disk_path: str | None
    cohort: Cohort
    error_code: str | None
    latitude: float | None
    longitude: float | None


class Partition(Document):
    schema_version: Literal["1.0"] = "1.0"
    source_system: Literal["max_bot_foto"] = "max_bot_foto"
    source_instance_id: str
    cohort: Cohort
    source_timezone: str
    partition_received_date: date
    generation_id: str
    produced_at: datetime
    as_of: datetime
    photo_count: int = Field(ge=0)
    items: list[PhotoRecord]


class FileRef(Document):
    file_ref: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PartitionRef(FileRef):
    received_date: date
    generation_id: str
    photo_count: int = Field(ge=0)


class Dictionary(Document):
    schema_version: Literal["1.0"] = "1.0"
    source_instance_id: str
    cohort: Cohort
    work_types: list[dict]
    statuses: list[str]
    storage_statuses: list[str]
    districts_geojson: dict


class Index(Document):
    schema_version: Literal["1.0"] = "1.0"
    source_system: Literal["max_bot_foto"] = "max_bot_foto"
    source_instance_id: str
    cohort: Cohort
    source_timezone: str
    published_at: datetime
    as_of: datetime
    index_generation_id: str
    photo_count: int = Field(ge=0)
    partitions: list[PartitionRef]
    dictionaries: FileRef


def json_bytes(value: dict) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def exchange_root(state: ExchangeState, cohort: str) -> str:
    external_cohort = "training" if cohort == "test" else cohort
    return f"disk:/{settings().exchange_folder}/{external_cohort}/{state.instance_id}"


def record(photo: Photo) -> PhotoRecord:
    return PhotoRecord(
        source_photo_id=str(photo.id),
        source_version=photo.version,
        received_at=photo.received_at,
        updated_at=photo.updated_at,
        photo_date=photo.photo_date,
        photo_time=photo.photo_time,
        max_chat_id=str(photo.max_chat_id),
        max_message_id=photo.max_message_id,
        district_id=str(photo.district_id) if photo.district_id else None,
        district_name=photo.district_name_snapshot,
        source_work_type_code=photo.work_type,
        classification_mode=photo.classification_mode,
        work_rule_version=photo.work_rule_version,
        fixed_work_type_snapshot=photo.fixed_work_type_snapshot,
        work_type_source=photo.work_type_source,
        classification_confidence=photo.ai_confidence,
        status=photo.status,
        review_reason=photo.review_reason or None,
        storage_status=photo.storage_status,
        duplicate_of=str(photo.duplicate_of) if photo.duplicate_of else None,
        sha256=photo.sha256,
        original_disk_path=None if photo.preview_removed_at is not None else photo.yandex_disk_path,
        cohort="training" if photo.cohort == "test" else photo.cohort,
        error_code=photo.processing_error,
        latitude=photo.latitude,
        longitude=photo.longitude,
    )


def prepare(publication_id: int):
    # A snapshot is committed before any network calls. Retries reuse these exact bytes/paths.
    with Session(engine(), expire_on_commit=False) as db:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        pub = db.get(Publication, publication_id)
        state = db.get(ExchangeState, 1)
        root = exchange_root(state, pub.cohort)
        register_existing(db, root)
        if pub.payload is not None:
            checked_files(pub, root)
            db.commit()
            return
        previous = {
            item.section: item
            for item in db.scalars(
                select(ExchangeFile)
                .where(ExchangeFile.root == root, ExchangeFile.status == "AVAILABLE")
                .distinct(ExchangeFile.section)
                .order_by(ExchangeFile.section, ExchangeFile.publication_id.desc())
            )
        }
        instant = now()
        identity = f"{state.instance_id}-{pub.cohort}"
        external_cohort = "training" if pub.cohort == "test" else pub.cohort
        generation = f"{pub.id:020d}"
        groups = defaultdict(list)
        for photo in db.scalars(select(Photo).where(Photo.cohort == pub.cohort).order_by(Photo.id)):
            day = photo.received_at.astimezone(ZoneInfo(state.source_timezone)).date()
            groups[day].append(record(photo))
        files, refs = [], []

        def add_file(path, document, reuse=False):
            value = document.model_dump(mode="json")
            old = previous.get(str(Path(path).parent)) if reuse else None
            if old and old.content_sha256 == content_hash(value):
                files.append({"file_ref": old.file_ref, "sha256": old.sha256, "document": old.document})
                return {"file_ref": old.file_ref, "sha256": old.sha256}
            digest = hashlib.sha256(json_bytes(value)).hexdigest()
            files.append({"file_ref": path, "sha256": digest, "document": value})
            return {"file_ref": path, "sha256": digest}

        for day, items in sorted(groups.items()):
            path = f"snapshots/{day}/{generation}.json"
            doc = Partition(
                source_instance_id=identity,
                cohort=external_cohort,
                source_timezone=state.source_timezone,
                partition_received_date=day,
                generation_id=generation,
                produced_at=instant,
                as_of=instant,
                photo_count=len(items),
                items=items,
            )
            file_ref = add_file(path, doc, reuse=True)
            refs.append(
                PartitionRef(
                    **file_ref,
                    received_date=day,
                    generation_id=Path(file_ref["file_ref"]).stem,
                    photo_count=len(items),
                )
            )
        features = []
        for did, name, active, geo in db.execute(
            select(
                District.id, District.name, District.active, func.ST_AsGeoJSON(District.geometry)
            ).order_by(District.id)
        ):
            features.append(
                {
                    "type": "Feature",
                    "id": str(did),
                    "properties": {
                        "source_district_id": str(did),
                        "name": name,
                        "active": active,
                        "geometry_sha256": hashlib.sha256(json_bytes(json.loads(geo))).hexdigest(),
                    },
                    "geometry": json.loads(geo),
                }
            )
        dictionary = Dictionary(
            source_instance_id=identity,
            cohort=external_cohort,
            work_types=[{"code": c, "name": n[0]} for c, n in work_catalog(db).items()],
            statuses=list(Status),
            storage_statuses=["PENDING", "ERROR", "SYNCED", "NOT_REQUIRED"],
            districts_geojson={"type": "FeatureCollection", "features": features},
        )
        dictionary_ref = FileRef(**add_file(f"dictionaries/{generation}.json", dictionary, reuse=True))
        index = Index(
            source_instance_id=identity,
            cohort=external_cohort,
            source_timezone=state.source_timezone,
            published_at=instant,
            as_of=instant,
            index_generation_id=generation,
            photo_count=sum(len(v) for v in groups.values()),
            partitions=refs,
            dictionaries=dictionary_ref,
        )
        index_ref = add_file(f"indexes/{generation}.json", index)
        pub.payload = {"root": root, "files": files}
        pub.index_path = f"{pub.payload['root']}/{index_ref['file_ref']}"
        pub.as_of, pub.photo_count, pub.status = instant, index.photo_count, "UPLOADING"
        register_manifest(db, pub, root)
        db.commit()


def publish(publication_id: int, disk: YandexDisk | None = None):
    # One source-wide publisher; session lock survives commits and is released on worker death.
    with engine().connect() as lock:
        lock.execute(text("SELECT pg_advisory_lock(7008, 1)"))
        lock.commit()
        try:
            with Session(engine()) as db:
                pub = db.get(Publication, publication_id)
                if pub.status in {"DONE", "SUPERSEDED", "PRUNING", "PRUNED", "RETIRED"}:
                    return
                state = db.get(ExchangeState, 1)
                attr = f"last_{pub.cohort}_publication_id"
                if (getattr(state, attr) or 0) > pub.id:
                    pub.status, pub.finished_at = "SUPERSEDED", now()
                    db.commit()
                    return
            try:
                prepare(publication_id)
                with Session(engine()) as db:
                    payload = db.get(Publication, publication_id).payload
                disk = disk or YandexDisk()
                with TemporaryDirectory(prefix="max-exchange-") as temp:
                    local = Path(temp) / "snapshot.json"
                    # The index is last. Existing generations remain readable throughout retries.
                    for item in payload["files"]:
                        data = json_bytes(item["document"])
                        if hashlib.sha256(data).hexdigest() != item["sha256"]:
                            raise RuntimeError("SNAPSHOT_CHECKSUM_MISMATCH")
                        target = f"{payload['root']}/{item['file_ref']}"
                        if int(Path(item["file_ref"]).stem) != publication_id and disk.matches(
                            target, item["sha256"]
                        ):
                            continue
                        local.write_bytes(data)
                        disk.upload(local, target, item["sha256"])
                with Session(engine()) as db:
                    pub = db.get(Publication, publication_id)
                    pub.status, pub.finished_at, pub.last_error = "DONE", now(), None
                    for item in db.scalars(select(ExchangeFile).where(ExchangeFile.publication_id == pub.id)):
                        item.status = "AVAILABLE"
                    state = db.get(ExchangeState, 1)
                    setattr(state, f"last_{pub.cohort}_publication_id", pub.id)
                    enqueue(db, "EXCHANGE_GC", pub.id, f"exchange-gc:{pub.id}")
                    job = db.scalar(select(Job).where(Job.dedupe_key == f"exchange-gc:{pub.id}"))
                    job.next_run_at = now() + timedelta(hours=settings().exchange_read_window_hours)
                    db.commit()
            except Exception as exc:
                with Session(engine()) as db:
                    pub = db.get(Publication, publication_id)
                    pub.status, pub.last_error = "RETRY", error_code(exc)
                    db.commit()
                raise
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(7008, 1)"))
            lock.commit()
