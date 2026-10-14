"""Recover manifests of obsolete service JSON after an interrupted folder move."""

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from app.config import settings
from app.exchange import Dictionary, Index, Partition


def recover_manifest(disk, root: str, expected: dict[str, str], instance_id: str) -> dict[str, str]:
    """Trust DB hashes or validated indexes belonging to this source, never arbitrary JSON."""
    files, folders = {}, [root]
    seen = {root}
    for folder in folders:
        for item in disk.folder_items(folder) or []:
            path = item.get("path", "")
            parsed = PurePosixPath(path)
            if str(parsed) != path or str(parsed.parent) != folder or ".." in parsed.parts or path in seen:
                raise RuntimeError("YANDEX_INVALID_SERVICE_PATH")
            seen.add(path)
            if item.get("type") == "dir":
                folders.append(path)
            elif item.get("type") == "file" and path.endswith(".json"):
                files[path] = item.get("sha256")
            else:
                raise RuntimeError("LEGACY_EXCHANGE_UNMANAGED_FILE")
    recovered = dict(expected)
    if any(
        not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in files.values()
    ):
        raise RuntimeError("LEGACY_EXCHANGE_INVALID_DOCUMENT")
    if any(path in recovered and recovered[path] != digest for path, digest in files.items()):
        raise RuntimeError("LEGACY_EXCHANGE_FILE_CHANGED")
    if all(path in recovered and recovered[path] == digest for path, digest in files.items()):
        return recovered

    def read(path, digest):
        with TemporaryDirectory(prefix="max-legacy-check-") as temp:
            local = Path(temp) / "document.json"
            disk.download(path, local)
            if local.stat().st_size > settings().max_file_bytes:
                raise RuntimeError("LEGACY_EXCHANGE_UNMANAGED_FILE")
            data = local.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeError("LEGACY_EXCHANGE_FILE_CHANGED")
        return json.loads(data)

    try:
        for path, digest in files.items():
            relative = PurePosixPath(path.removeprefix(root + "/"))
            parts = relative.parts
            if len(parts) != 4 or parts[0] not in {"test", "training", "production"}:
                continue
            if parts[1] != instance_id or parts[2] != "indexes":
                continue
            cohort = "production" if parts[0] == "production" else "test"
            identity = f"{instance_id}-{cohort}"
            value = read(path, digest)
            if value.get("cohort") == "test":
                value["cohort"] = "training"
            index = Index.model_validate(value)
            if index.source_instance_id != identity or parts[3] != index.index_generation_id + ".json":
                raise ValueError("source mismatch")
            recovered[path] = digest
            base = str(PurePosixPath(path).parent.parent)
            references = [(index.dictionaries, Dictionary)] + [(ref, Partition) for ref in index.partitions]
            for ref, model in references:
                relative = PurePosixPath(ref.file_ref)
                if relative.is_absolute() or str(relative) != ref.file_ref or ".." in relative.parts:
                    raise ValueError("invalid reference")
                if model is Dictionary:
                    valid = ref.file_ref == f"dictionaries/{index.index_generation_id}.json"
                else:
                    valid = ref.file_ref == f"snapshots/{ref.received_date}/{index.index_generation_id}.json"
                if not valid:
                    raise ValueError("invalid generation")
                target = f"{base}/{ref.file_ref}"
                if target not in files:
                    continue  # An earlier retirement may have already removed part of this generation.
                if files[target] != ref.sha256 or (target in recovered and recovered[target] != ref.sha256):
                    raise RuntimeError("LEGACY_EXCHANGE_FILE_CHANGED")
                document = read(target, ref.sha256)
                if document.get("cohort") == "test":
                    document["cohort"] = "training"
                if model is Partition:
                    if "published_at" in document and "produced_at" not in document:
                        document["produced_at"] = document.pop("published_at")
                    for item in document.get("items", []):
                        if item.get("cohort") == "test":
                            item["cohort"] = "training"
                validated = model.model_validate(document)
                if validated.source_instance_id != identity or validated.cohort != index.cohort:
                    raise ValueError("source mismatch")
                if model is Partition and (
                    validated.generation_id != index.index_generation_id
                    or validated.partition_received_date != ref.received_date
                    or validated.photo_count != ref.photo_count
                    or validated.photo_count != len(validated.items)
                ):
                    raise ValueError("partition mismatch")
                recovered[target] = ref.sha256
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise RuntimeError("LEGACY_EXCHANGE_INVALID_DOCUMENT") from exc
    if any(path not in recovered or recovered[path] != digest for path, digest in files.items()):
        raise RuntimeError("LEGACY_EXCHANGE_UNMANAGED_FILE")
    return recovered
