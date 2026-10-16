"""Checkpoint retention uses real files and PostgreSQL locks, never live service data."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import ml, model_storage
from app.config import settings
from app.db import engine
from app.media import media_path
from app.models import Audit, ModelVersion, Photo
from tests.test_ml import seed_dataset


def checkpoint(db, status="SUPERSEDED", architecture=ml.ARCHITECTURE, saved=True):
    version = ModelVersion(
        status=status,
        dataset_fingerprint="a" * 64,
        sample_count=50,
        labels_snapshot={"photo-hash": ml.CODES[0]},
        metrics={"architecture": architecture, "macro_f1": 0.9},
        supported_classes=ml.CODES[:2],
        model_sha256="b" * 64,
    )
    db.add(version)
    db.flush()
    path = settings().data_dir / "models" / f"version-{version.id}" / "weights.pt"
    path.parent.mkdir(parents=True, exist_ok=True)
    if saved:
        path.write_bytes(b"synthetic checkpoint")
        version.model_path = str(path)
    db.commit()
    return version, path


def test_keeps_current_and_three_successful_versions_and_all_training_data(db):
    seed_dataset(db)
    photo = db.scalar(select(Photo).order_by(Photo.id))
    preview = media_path(photo.id, True)
    preview_bytes = preview.read_bytes()
    before_dataset = ml.snapshot(ml.collect_examples(db)[0])
    versions = [checkpoint(db) for _ in range(5)]
    active, active_path = checkpoint(db, "ACTIVE")
    discarded = [checkpoint(db, status) for status in ["REJECTED", "ERROR", "INTERRUPTED"]]
    oldest, oldest_path = versions[0]
    oldest_path.with_suffix(".tmp").write_bytes(b"partial")
    extra = oldest_path.parent / "operator-notes.txt"
    extra.write_text("preserve unknown files")
    backbone = active_path.parent.parent / "resnet18-f37072fd.pth"
    backbone.write_bytes(b"generic backbone")
    spool = settings().data_dir / "spool" / "original.jpg"
    spool.parent.mkdir()
    spool.write_bytes(b"original")

    assert model_storage.cleanup_model_files() == 5
    db.expire_all()
    for version, path in versions[:2] + discarded:
        assert not path.exists()
        assert version.model_path is None and version.weights_removed_at is not None
        assert version.dataset_fingerprint == "a" * 64
        assert version.labels_snapshot == {"photo-hash": ml.CODES[0]}
        assert version.metrics["macro_f1"] == 0.9
        assert version.model_sha256 == "b" * 64
    assert oldest.status == "SUPERSEDED"
    assert not oldest_path.with_suffix(".tmp").exists()
    assert extra.read_text() == "preserve unknown files"
    assert not versions[1][1].parent.exists()  # Only empty version directories are removed.
    for version, path in [*versions[2:], (active, active_path)]:
        assert path.is_file() and version.model_path == str(path)
        assert version.weights_removed_at is None
    assert [v.status for v, _ in discarded] == ["REJECTED", "ERROR", "INTERRUPTED"]
    assert backbone.read_bytes() == b"generic backbone"
    assert spool.read_bytes() == b"original"
    assert preview.read_bytes() == preview_bytes
    assert ml.snapshot(ml.collect_examples(db)[0]) == before_dataset
    audits = list(db.scalars(select(Audit).where(Audit.action == "MODEL_WEIGHTS_REMOVED")))
    assert len(audits) == 5 and all(a.photo_id is None for a in audits)
    assert db.scalar(select(func.count()).select_from(ModelVersion)) == 9
    assert ml.latest_evaluated(db).id == discarded[0][0].id
    assert model_storage.cleanup_model_files() == 0
    assert db.scalar(select(func.count()).select_from(Audit)) == 5


def test_without_active_model_keeps_four_latest_completed_candidates(db):
    versions = [checkpoint(db, "REJECTED") for _ in range(6)]
    running, running_path = checkpoint(db, "TRAINING")
    assert model_storage.cleanup_model_files() == 2
    assert not any(p.exists() for _, p in versions[:2])
    assert all(p.is_file() for _, p in versions[2:])
    assert running_path.is_file()
    db.refresh(running)
    assert running.status == "TRAINING" and running.weights_removed_at is None


def test_missing_active_weights_preserve_all_fallbacks(db):
    versions = [checkpoint(db) for _ in range(5)]
    active, path = checkpoint(db, "ACTIVE")
    path.unlink()
    assert model_storage.cleanup_model_files() == 0
    assert all(p.is_file() for _, p in versions)
    db.refresh(active)
    assert active.model_path == str(path) and active.weights_removed_at is None


def test_missing_or_incompatible_previous_weights_do_not_displace_good_fallbacks(db):
    versions = [checkpoint(db) for _ in range(4)]
    missing, path = checkpoint(db)
    path.unlink()
    incompatible, incompatible_path = checkpoint(db, architecture="old-catalog")
    checkpoint(db, "ACTIVE")
    assert model_storage.cleanup_model_files() == 3
    assert not versions[0][1].exists() and not incompatible_path.exists()
    assert all(p.is_file() for _, p in versions[1:])
    db.refresh(missing)
    assert missing.weights_removed_at and missing.model_path is None
    db.refresh(incompatible)
    assert incompatible.metrics["architecture"] == "old-catalog"


def test_failed_partial_files_removed_but_running_and_untracked_files_preserved(db):
    failed, partial = checkpoint(db, "INTERRUPTED", saved=False)
    partial.with_suffix(".tmp").write_bytes(b"incomplete save")
    running, running_path = checkpoint(db, "TRAINING", saved=False)
    running_path.with_suffix(".tmp").write_bytes(b"in progress")
    untracked = settings().data_dir / "models" / "version-99999" / "weights.pt"
    untracked.parent.mkdir()
    untracked.write_bytes(b"not tracked")
    checkpoint(db, "ACTIVE")
    assert model_storage.cleanup_model_files() == 1
    db.refresh(failed)
    assert failed.weights_removed_at and not partial.parent.exists()
    assert running_path.with_suffix(".tmp").is_file() and untracked.is_file()
    db.refresh(running)
    assert running.status == "TRAINING" and running.weights_removed_at is None


@pytest.mark.parametrize("unsafe", ["external", "directory_symlink", "file_symlink", "temporary_symlink"])
def test_cleanup_never_follows_external_paths_or_symlinks(db, tmp_path, unsafe):
    version, path = checkpoint(db, "REJECTED")
    external = tmp_path / "outside" / "weights.pt"
    external.parent.mkdir()
    external.write_bytes(b"outside checkpoint")
    if unsafe == "external":
        version.model_path = str(external)
        db.commit()
    elif unsafe == "directory_symlink":
        path.unlink()
        path.parent.rmdir()
        path.parent.symlink_to(external.parent, target_is_directory=True)
    elif unsafe == "file_symlink":
        path.unlink()
        path.symlink_to(external)
    else:
        path.with_suffix(".tmp").symlink_to(external)
    checkpoint(db, "ACTIVE")
    assert model_storage.cleanup_model_files() == 0
    assert external.read_bytes() == b"outside checkpoint"
    db.refresh(version)
    assert version.weights_removed_at is None


def test_protects_file_referenced_by_other_record_and_custom_backbone(db, monkeypatch):
    first, first_path = checkpoint(db, "REJECTED")
    backbone_version, backbone_path = checkpoint(db, "ERROR")
    reference, _ = checkpoint(db, "TRAINING", saved=False)
    reference.model_path = str(first_path)
    db.commit()
    monkeypatch.setenv("ML_BACKBONE_PATH", str(backbone_path))
    settings.cache_clear()
    checkpoint(db, "ACTIVE")
    assert model_storage.cleanup_model_files() == 0
    assert first_path.is_file() and backbone_path.is_file()
    for version in [first, backbone_version]:
        db.refresh(version)
        assert version.weights_removed_at is None


def test_unlink_failure_is_retried_and_does_not_disable_active_model(db, monkeypatch):
    rejected, path = checkpoint(db, "REJECTED")
    active, active_path = checkpoint(db, "ACTIVE")
    original_unlink = Path.unlink

    def fail_one_path(self, *args, **kwargs):
        if self == path:
            raise PermissionError("synthetic permission failure")
        return original_unlink(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_one_path)
        assert model_storage.cleanup_model_files() == 0
    db.refresh(rejected)
    assert rejected.model_path == str(path) and rejected.weights_removed_at is None
    assert model_storage.cleanup_model_files() == 1
    db.refresh(active)
    assert active.status == "ACTIVE" and active_path.is_file()


def test_db_failure_after_file_removal_is_repaired_next_cycle(db, monkeypatch):
    version, path = checkpoint(db, "REJECTED")
    checkpoint(db, "ACTIVE")
    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", lambda _: (_ for _ in ()).throw(RuntimeError("synthetic failure")))
        assert model_storage.cleanup_model_files() == 0
    assert not path.exists()
    db.refresh(version)
    assert version.model_path == str(path) and version.weights_removed_at is None
    assert model_storage.cleanup_model_files() == 1
    db.refresh(version)
    assert version.weights_removed_at and version.model_path is None
    audit = db.scalar(select(Audit).where(Audit.action == "MODEL_WEIGHTS_REMOVED"))
    assert audit.new_value["file_was_missing"] is True


@pytest.mark.parametrize("key,shared", [(7005, False), (model_storage.MODEL_FILE_LOCK, True)])
def test_cleanup_skips_training_or_model_loading_and_releases_its_locks(db, key, shared):
    _, path = checkpoint(db, "REJECTED")
    checkpoint(db, "ACTIVE")
    suffix = "_shared" if shared else ""
    with engine().connect() as other:
        other.execute(text(f"SELECT pg_advisory_lock{suffix}(:key, 1)"), {"key": key})
        other.commit()
        try:
            assert model_storage.cleanup_model_files() == 0
            assert path.is_file()
        finally:
            other.execute(text(f"SELECT pg_advisory_unlock{suffix}(:key, 1)"), {"key": key})
            other.commit()
    assert model_storage.cleanup_model_files() == 1
    with engine().connect() as other:
        for lock_key in [7005, model_storage.MODEL_FILE_LOCK]:
            assert other.scalar(text("SELECT pg_try_advisory_lock(:key, 1)"), {"key": lock_key})
            other.execute(text("SELECT pg_advisory_unlock(:key, 1)"), {"key": lock_key})
        other.commit()


def test_classifier_holds_shared_lock_until_weights_loaded(db, monkeypatch):
    _, old_path = checkpoint(db, "REJECTED")
    checkpoint(db, "ACTIVE")
    entered, finish = Event(), Event()

    def delayed_load(*_):
        entered.set()
        assert finish.wait(5)
        raise RuntimeError("STOP_AFTER_LOADING")

    monkeypatch.setattr(ml, "load_model", delayed_load)
    with ThreadPoolExecutor(max_workers=1) as executor:
        task = executor.submit(ml.LocalClassifier().classify, Path("unused"))
        try:
            assert entered.wait(5)
            assert model_storage.cleanup_model_files() == 0
            assert old_path.is_file()
        finally:
            finish.set()
        with pytest.raises(RuntimeError, match="STOP_AFTER_LOADING"):
            task.result(timeout=5)
    assert model_storage.cleanup_model_files() == 1


def test_trainer_checks_retention_even_when_auto_training_disabled(db, monkeypatch):
    import signal

    from app import worker

    _, path = checkpoint(db, "REJECTED")
    checkpoint(db, "ACTIVE")
    monkeypatch.setenv("ML_AUTO_TRAIN", "false")
    settings.cache_clear()
    handlers = {}
    monkeypatch.setattr(signal, "signal", lambda key, handler: handlers.update({key: handler}))

    def stop_after_check(**_):
        handlers[signal.SIGTERM]()
        return True

    monkeypatch.setattr(worker, "run_once", stop_after_check)
    ml.main()
    assert not path.exists()


def test_learning_api_reports_retained_and_removed_weights(admin, db):
    removed, _ = checkpoint(db, "REJECTED")
    active, _ = checkpoint(db, "ACTIVE")
    model_storage.cleanup_model_files()
    payload = admin.get("/api/ml").json()
    assert payload["retention"] == {"previous_versions": 3}
    assert payload["active"]["id"] == active.id and payload["active"]["weights_available"]
    assert payload["active"]["weights_removed_at"] is None
    old = next(run for run in payload["runs"] if run["id"] == removed.id)
    assert old["status"] == "REJECTED" and not old["weights_available"] and old["weights_removed_at"]
    assert "model_path" not in old and "labels_snapshot" not in old
