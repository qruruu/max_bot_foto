import hashlib
from copy import deepcopy

import httpx
import pytest
from test_exchange import publication
from test_exchange_housekeeping import Disk, seed_old_exchange
from test_integration import FakeMax, GoodAI, GoodOCR, intake_photo, setup_chat, setup_district

from app.exchange import json_bytes, publish
from app.exchange_housekeeping import organize_archive
from app.models import ExchangeState
from app.processing import error_code, process_photo

pytestmark = pytest.mark.integration


def orphan_legacy_generation(db):
    setup_chat(db)
    intake_photo(db)
    disk, pub = Disk(), publication(db)
    publish(pub.id, disk)
    db.refresh(pub)
    live = dict(disk.files)
    state = db.get(ExchangeState, 1)
    root = f"disk:/MAX_PHOTOS_ARM_EXCHANGE/legacy/ARM_EXCHANGE/test/{state.instance_id}"
    hashes = {}
    for item in pub.payload["files"]:
        doc = deepcopy(item["document"])
        doc["cohort"] = "test"
        ref = item["file_ref"]
        if ref.startswith("snapshots/"):
            doc["published_at"] = doc.pop("produced_at")
            for photo in doc["items"]:
                photo["cohort"] = "test"
        if ref.startswith("indexes/"):
            for target in [doc["dictionaries"], *doc["partitions"]]:
                target["sha256"] = hashes[target["file_ref"]]
        data = json_bytes(doc)
        hashes[ref] = hashlib.sha256(data).hexdigest()
        disk.files[root + "/" + ref] = data
    pub.status, pub.payload, pub.index_path = "RETIRED", None, None
    db.commit()
    return disk, root, live


def test_recovers_copied_generation_after_manifest_was_discarded(db):
    disk, root, live = orphan_legacy_generation(db)
    organize_archive(disk)
    assert disk.files == live
    assert not any(path.startswith(root + "/") for path in disk.files)
    organize_archive(disk)
    assert disk.files == live


def test_recovers_folder_move_before_database_path_commit(db):
    disk = Disk()
    pub, old_root = seed_old_exchange(db, disk)
    legacy_root = old_root.replace(
        "disk:/MAX_PHOTOS/ARM_EXCHANGE", "disk:/MAX_PHOTOS_ARM_EXCHANGE/legacy/ARM_EXCHANGE"
    )
    disk.move_folder(old_root, legacy_root)
    organize_archive(disk)
    db.refresh(pub)
    assert pub.status == "RETIRED" and pub.payload is None
    assert not disk.files


def test_failed_copy_retirement_keeps_all_database_hashes_for_retry(db):
    disk = Disk()
    pub, old_root = seed_old_exchange(db, disk)
    copied = old_root.replace(
        "disk:/MAX_PHOTOS/ARM_EXCHANGE", "disk:/MAX_PHOTOS_ARM_EXCHANGE/legacy/ARM_EXCHANGE"
    )
    disk.files[copied + "/indexes/1.json"] = disk.files[pub.index_path]
    remove = disk.trash_legacy_exchange_folder

    def fail_legacy(path, expected):
        if "/legacy/" in path:
            raise RuntimeError("network unavailable")
        remove(path, expected)

    disk.trash_legacy_exchange_folder = fail_legacy
    with pytest.raises(RuntimeError, match="network"):
        organize_archive(disk)
    db.refresh(pub)
    assert pub.payload is not None and pub.status == "DONE"
    disk.trash_legacy_exchange_folder = remove
    organize_archive(disk)
    db.refresh(pub)
    assert pub.status == "RETIRED" and not disk.files


@pytest.mark.parametrize(
    "case", ["foreign_source", "changed_hash", "extra_photo", "invalid_json", "extra_json"]
)
def test_uncertain_legacy_files_never_get_deleted_but_empty_photo_folders_are_cleaned(db, case):
    disk, root, _ = orphan_legacy_generation(db)
    if case == "foreign_source":
        path = next(p for p in disk.files if p.startswith(root) and "/indexes/" in p)
        import json

        doc = json.loads(disk.files[path])
        doc["source_instance_id"] = "unrelated-instance-test"
        disk.files[path] = json_bytes(doc)
    elif case == "changed_hash":
        path = next(p for p in disk.files if p.startswith(root) and "/dictionaries/" in p)
        disk.files[path] += b" "
    elif case == "invalid_json":
        path = next(p for p in disk.files if p.startswith(root) and "/indexes/" in p)
        disk.files[path] = b"not JSON"
    else:
        disk.files[root + ("/original.jpg" if case == "extra_photo" else "/notes.json")] = b"unknown file"
    empty = "disk:/MAX_PHOTOS/2026-04-20/old-chat/empty"
    disk.remember_parents(empty + "/removed.jpg")
    before = dict(disk.files)
    with pytest.raises(RuntimeError):
        organize_archive(disk)
    assert disk.files == before
    assert empty in disk.deleted_folders


def test_empty_numbered_roots_are_cleaned_but_nonempty_copies_and_main_roots_remain(db):
    disk = Disk()
    disk.folders.update(
        {"disk:/", "disk:/MAX_PHOTOS", "disk:/MAX_PHOTOS (1)", "disk:/MAX_PHOTOS_ARM_EXCHANGE (1)"}
    )
    disk.files["disk:/MAX_PHOTOS (2)/original.jpg"] = b"original"
    organize_archive(disk)
    assert "disk:/MAX_PHOTOS (1)" in disk.deleted_folders
    assert "disk:/MAX_PHOTOS_ARM_EXCHANGE (1)" in disk.deleted_folders
    assert "disk:/MAX_PHOTOS" in disk.folders
    assert disk.files["disk:/MAX_PHOTOS (2)/original.jpg"] == b"original"


@pytest.mark.parametrize("old_folder", ["old-chat", "ТЕСТОВЫЕ/old-chat"])
def test_one_locked_photo_does_not_prevent_other_photos_and_empty_folders(db, old_folder):
    setup_chat(db)
    setup_district(db)
    disk = Disk()
    photos = [intake_photo(db, mid) for mid in ("locked", "normal")]
    for photo, color in zip(photos, ("green", "blue"), strict=True):
        process_photo(photo.id, FakeMax(color), disk, GoodOCR(), GoodAI())
        db.refresh(photo)
        source = f"disk:/MAX_PHOTOS/{old_folder}/original_{photo.id}.png"
        disk.files[source] = disk.files.pop(photo.yandex_disk_path)
        photo.yandex_disk_path = source
    db.commit()
    locked_path = photos[0].yandex_disk_path
    move = disk.move

    def locked(source, target, digest):
        if source == locked_path:
            response = httpx.Response(423, request=httpx.Request("POST", "https://example.invalid"))
            response.raise_for_status()
        move(source, target, digest)

    disk.move = locked
    with pytest.raises(httpx.HTTPStatusError):
        organize_archive(disk)
    for photo in photos:
        db.refresh(photo)
    assert photos[0].processing_error == "HTTP_423"
    assert photos[0].yandex_disk_path == locked_path and locked_path in disk.files
    assert photos[1].storage_status == "SYNCED" and "/old-chat/" not in photos[1].yandex_disk_path


def test_restored_original_with_unchanged_path_clears_storage_error(db):
    setup_chat(db)
    setup_district(db)
    disk, photo = Disk(), intake_photo(db)
    process_photo(photo.id, FakeMax(), disk, GoodOCR(), GoodAI())
    db.refresh(photo)
    path = photo.yandex_disk_path
    photo.storage_status, photo.processing_error = "ERROR", "ORIGINAL_MISSING"
    db.commit()
    organize_archive(disk)
    db.refresh(photo)
    assert photo.yandex_disk_path == path and photo.storage_status == "SYNCED"
    assert photo.processing_error is None


def test_logs_keep_specific_application_codes_without_private_exception_text():
    assert error_code(RuntimeError("LEGACY_EXCHANGE_UNMANAGED_FILE")) == "LEGACY_EXCHANGE_UNMANAGED_FILE"
    assert error_code(RuntimeError("https://private.invalid/?token=secret")) == "RuntimeError"
    assert error_code(RuntimeError("SECRET_TOKEN_VALUE")) == "RuntimeError"
