"""Validate manifests and track data generations independently of publication indexes."""

import hashlib
import re
from pathlib import PurePosixPath

from sqlalchemy import select

from app.models import ExchangeFile, Publication


def content_hash(document):
    from app.exchange import json_bytes

    # Partition timestamps describe its creation, not a change to its records.
    value = {k: v for k, v in document.items() if k not in {"generation_id", "produced_at", "as_of"}}
    return hashlib.sha256(json_bytes(value)).hexdigest()


def checked_files(pub, root):
    """Accept only a complete, consistent index and its exact referenced data files."""
    from app.exchange import Dictionary, Index, Partition, json_bytes

    if not pub.payload or pub.payload.get("root") != root:
        raise ValueError("LEGACY_PUBLICATION")
    files = pub.payload["files"]
    generation = f"{pub.id:020d}"
    identity = f"{root.rsplit('/', 1)[-1]}-{pub.cohort}"
    cohort = "training" if pub.cohort == "test" else pub.cohort
    documents = {}
    for item in files:
        ref = item["file_ref"]
        path = PurePosixPath(ref)
        if (
            path.is_absolute()
            or ".." in path.parts
            or str(path) != ref
            or not re.fullmatch(r"[0-9]{20}\.json", path.name)
            or not 0 < int(path.stem) <= pub.id
            or ref in documents
        ):
            raise ValueError("INVALID_EXCHANGE_REFERENCE")
        kind = path.parts[0]
        model = {"indexes": Index, "snapshots": Partition, "dictionaries": Dictionary}.get(kind)
        if model is None or len(path.parts) != (3 if kind == "snapshots" else 2):
            raise ValueError("INVALID_EXCHANGE_REFERENCE")
        doc = model.model_validate(item["document"])
        if doc.source_instance_id != identity or doc.cohort != cohort:
            raise ValueError("INVALID_EXCHANGE_SOURCE")
        if kind == "snapshots" and (
            str(doc.partition_received_date) != path.parts[1]
            or doc.generation_id != path.stem
            or doc.photo_count != len(doc.items)
            or any(record.cohort != cohort for record in doc.items)
        ):
            raise ValueError("INVALID_EXCHANGE_PARTITION")
        if hashlib.sha256(json_bytes(item["document"])).hexdigest() != item["sha256"]:
            raise ValueError("INVALID_EXCHANGE_CHECKSUM")
        documents[ref] = (item, doc)
    index_ref = f"indexes/{generation}.json"
    if not files or files[-1]["file_ref"] != index_ref or pub.index_path != f"{root}/{index_ref}":
        raise ValueError("INVALID_INDEX_ORDER")
    index = documents[index_ref][1]
    if (
        index.index_generation_id != generation
        or index.photo_count != sum(p.photo_count for p in index.partitions)
        or len({p.received_date for p in index.partitions}) != len(index.partitions)
    ):
        raise ValueError("INVALID_EXCHANGE_INDEX")
    expected = {index_ref}
    for ref in [*index.partitions, index.dictionaries]:
        if ref.file_ref in expected or ref.file_ref not in documents:
            raise ValueError("INVALID_EXCHANGE_REFERENCE")
        item, doc = documents[ref.file_ref]
        if item["sha256"] != ref.sha256:
            raise ValueError("INVALID_EXCHANGE_CHECKSUM")
        if ref is index.dictionaries:
            if not isinstance(doc, Dictionary):
                raise ValueError("INVALID_EXCHANGE_REFERENCE")
        elif (
            not isinstance(doc, Partition)
            or doc.generation_id != ref.generation_id
            or doc.partition_received_date != ref.received_date
            or doc.photo_count != ref.photo_count
            or doc.source_timezone != index.source_timezone
        ):
            raise ValueError("INVALID_EXCHANGE_REFERENCE")
        expected.add(ref.file_ref)
    if expected != set(documents):
        raise ValueError("UNREFERENCED_EXCHANGE_FILE")
    return files


def register_manifest(db, pub, root):
    files = checked_files(pub, root)
    for item in files[:-1]:
        ref = item["file_ref"]
        creator_id = int(PurePosixPath(ref).stem)
        creator = db.get(Publication, creator_id)
        if (
            not creator
            or creator.cohort != pub.cohort
            or (creator_id != pub.id and creator.status not in {"DONE", "PRUNING", "PRUNED"})
        ):
            raise ValueError("INVALID_EXCHANGE_OWNER")
        stored = db.scalar(
            select(ExchangeFile).where(ExchangeFile.root == root, ExchangeFile.file_ref == ref)
        )
        if stored is None:
            db.add(
                ExchangeFile(
                    publication_id=creator_id,
                    root=root,
                    file_ref=ref,
                    section=str(PurePosixPath(ref).parent),
                    sha256=item["sha256"],
                    content_sha256=content_hash(item["document"]),
                    document=item["document"],
                    status="AVAILABLE" if creator.status == "DONE" else "PENDING",
                )
            )
            db.flush()
        elif stored.sha256 != item["sha256"] or stored.status in {"DELETING", "DELETED"}:
            raise ValueError("INVALID_EXCHANGE_FILE_STATE")
    pub.payload = {**pub.payload, "registry_version": 1}


def register_existing(db, root):
    # Old manifests are imported once; retired payloads need not be kept to retain data files.
    pubs = db.scalars(
        select(Publication)
        .where(
            Publication.payload["root"].astext == root,
            Publication.payload["registry_version"].astext.is_(None),
        )
        .order_by(Publication.id)
    )
    for pub in pubs:
        register_manifest(db, pub, root)
