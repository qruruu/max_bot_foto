"""Check the delivered ARM contract even without a PostgreSQL server."""

import hashlib
import json
from pathlib import Path

from app.exchange import Dictionary, Index, Partition, PhotoRecord

ROOT = Path(__file__).parents[2] / "docs/exchange"


def test_documented_schemas_match_runtime():
    for model, name in [
        (PhotoRecord, "photo"),
        (Partition, "partition"),
        (Index, "index"),
        (Dictionary, "dictionary"),
    ]:
        schema = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
        assert schema.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
        assert schema == model.model_json_schema()


def test_synthetic_examples_validate_and_index_hashes_match():
    examples = ROOT / "examples"
    records = []
    for path in sorted(examples.glob("[0-9]*.json")):
        part = Partition.model_validate_json(path.read_bytes())
        assert part.photo_count == len(part.items) == 1
        assert part.source_instance_id.endswith(part.cohort)
        records += part.items
    assert len(records) >= 8
    assert {"ACCEPTED", "NEEDS_REVIEW", "DUPLICATE", "ERROR", "SPAM", "RECEIVED"} <= {
        i.status for i in records
    }
    assert {"test", "production"} == {i.cohort for i in records}
    index = Index.model_validate_json((examples / "index.json").read_bytes())
    for ref in [*index.partitions, index.dictionaries]:
        assert hashlib.sha256((examples / ref.file_ref).read_bytes()).hexdigest() == ref.sha256
    Dictionary.model_validate_json((examples / index.dictionaries.file_ref).read_bytes())
    original, corrected = (
        records[0],
        next(i for i in records if i.source_photo_id == records[0].source_photo_id and i.source_version > 1),
    )
    assert corrected.received_at == original.received_at
    assert corrected.photo_date != original.photo_date and corrected.work_type_source == "OPERATOR"
