"""Local training/inference tests. Synthetic fixtures never enter production datasets."""

import hashlib
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from app import ml
from app.config import settings
from app.domain import now
from app.media import digest_file, media_path
from app.models import Inbox, Job, ModelVersion, Photo, User


def examples(per_class=60):
    return [
        ml.Example(
            i + 1, hashlib.sha256(str(i).encode()).hexdigest(), ml.CODES[i // per_class], Path("unused")
        )
        for i in range(per_class * 2)
    ]


def test_holdout_is_stable_across_corrections_and_new_data():
    data = examples()
    old = ml.snapshot(data)
    corrected = ml.Example(data[0].photo_id, data[0].sha256, ml.CODES[2], data[0].path)
    assert corrected.validation == data[0].validation
    assert ml.changed_labels(ml.snapshot([corrected, *data[1:]]), old) == 1
    assert ml.changed_labels(ml.snapshot(data[1:]), old) == 1
    assert ml.fingerprint(old) == ml.fingerprint(ml.snapshot(list(reversed(data))))
    plan = ml.training_plan(data)
    assert plan["ready"] and plan["sample_count"] == 120
    assert plan["train_count"] + plan["validation_count"] == 120
    assert not ml.training_plan(data[:10])["ready"]


def test_promotion_requires_quality_without_regression():
    good = ml.metrics_for([0, 0, 0, 1, 1, 1], [0, 0, 0, 1, 1, 1], ml.CODES[:2])
    bad = ml.metrics_for([0, 0, 0, 1, 1, 1], [0, 0, 1, 0, 0, 0], ml.CODES[:2])
    assert ml.supported_classes(good) == ml.CODES[:2]
    assert ml.promotion_allowed(good, ml.CODES[:2], None, [])
    assert not ml.promotion_allowed(bad, ml.CODES[:1], good, ml.CODES[:2])
    assert not ml.promotion_allowed(good, ml.CODES[:1], good, ml.CODES[:2])
    assert not ml.promotion_allowed({"macro_f1": 0.8}, ml.CODES[:2], good, ml.CODES[:2])


def test_ambiguous_unsupported_and_multiple_predictions_go_to_review():
    def row(index, confidence):
        values = [(1 - confidence) / 21] * 22
        values[index] = confidence
        return values

    assert ml.interpret_probabilities([row(0, 0.95)], ml.CODES[:2], 0.8).result == "SINGLE"
    assert ml.interpret_probabilities([row(0, 0.6)], ml.CODES[:2], 0.8).result == "UNKNOWN"
    assert ml.interpret_probabilities([row(2, 0.99)], ml.CODES[:2], 0.8).result == "UNKNOWN"
    result = ml.interpret_probabilities([row(0, 0.95), row(1, 0.96)], ml.CODES[:2], 0.8)
    assert result.result == "MULTIPLE" and result.work_type is None


def test_actual_resnet_weights_roundtrip_and_checksum(tmp_path):
    torch, _, _ = ml.torch_modules()
    model = ml.network()
    batch = torch.stack([ml.transform_image(Image.new("RGB", (320, 170), "green"))] * 2)
    model.eval()
    loss = torch.nn.CrossEntropyLoss()(model(batch), torch.tensor([0, 1]))
    loss.backward()
    assert model.fc.weight.grad.abs().sum() > 0
    path = tmp_path / "weights.pt"
    torch.save(model.state_dict(), path)
    restored = ml.load_model(str(path), digest_file(path))
    with torch.inference_mode():
        assert torch.equal(model(batch), restored(batch))
    with pytest.raises(RuntimeError, match="MODEL_CHECKSUM_MISMATCH"):
        ml.load_model(str(path), "0" * 64)
    ml.load_model.cache_clear()


def test_no_model_is_explicit_unknown_without_network(db, monkeypatch):
    monkeypatch.setattr(ml, "torch_modules", lambda: pytest.fail("Bootstrap must not load a fake model"))
    result = ml.LocalClassifier().classify(Path("does-not-need-to-exist"))
    assert result.classification.result == "UNKNOWN"
    assert result.raw == {"provider": "local", "reason": "MODEL_NOT_TRAINED", "model_id": None}


def seed_dataset(db, per_class=25):
    user = User(login="teacher", name="Teacher", role="OPERATOR", password_hash="not-a-login")
    inbox = Inbox(max_chat_id=123, message_id="training-fixture", payload={})
    db.add_all([user, inbox])
    db.flush()
    for i, example in enumerate(examples(per_class)):
        photo = Photo(
            inbox_id=inbox.id,
            attachment_index=i,
            max_chat_id=123,
            chat_name="Test",
            max_message_id="training-fixture",
            sha256=example.sha256,
            analyzed_at=now(),
            status="NEEDS_REVIEW",
            work_type=example.label,
            work_type_source="OPERATOR",
            reviewed_by=user.id,
        )
        db.add(photo)
        db.flush()
        Image.new("RGB", (80, 60), "red" if i < per_class else "green").save(media_path(photo.id, True))
    db.commit()


def small_training_config(monkeypatch):
    for key, value in {
        "ML_MIN_SAMPLES": "40",
        "ML_MIN_PER_CLASS": "20",
        "ML_EPOCHS": "5",
        "ML_LEARNING_RATE": "0.05",
    }.items():
        monkeypatch.setenv(key, value)
    settings.cache_clear()


def test_dataset_uses_only_explicit_operator_work_labels(db):
    seed_dataset(db)
    photos = list(db.scalars(select(Photo).order_by(Photo.id)))
    photos[0].work_type_source = "AI"
    photos[1].reviewed_by = None
    photos[2].analyzed_at = None
    photos[3].status = "REJECTED"
    media_path(photos[4].id, True).unlink()
    db.commit()
    data, missing = ml.collect_examples(db)
    assert len(data) == 45 and missing == 1
    assert not {p.id for p in photos[:5]} & {e.photo_id for e in data}


def test_train_save_activate_classify_and_queue_isolation(db, monkeypatch):
    small_training_config(monkeypatch)
    seed_dataset(db)
    torch, _, _ = ml.torch_modules()

    class TinyNetwork(torch.nn.Module):
        """Fast differentiable test backbone; production always uses actual ResNet18."""

        def __init__(self):
            super().__init__()
            self.fc = torch.nn.Linear(3, 22)
            with torch.no_grad():
                self.fc.weight.zero_()
                self.fc.bias.fill_(-10)
                self.fc.bias[:2].zero_()

        def forward(self, batch):
            return self.fc(batch.mean(dim=(2, 3)))

    monkeypatch.setattr(ml, "prepare_backbone", lambda: None)
    monkeypatch.setattr(ml, "network", lambda *args: TinyNetwork())
    assert ml.schedule_training()
    assert not ml.schedule_training()
    from app.worker import run_once

    assert not run_once()  # Intake workers never consume a long-running training job.
    assert run_once(kinds=["TRAIN"])
    db.expire_all()
    version = db.scalar(select(ModelVersion))
    job = db.scalar(select(Job))
    assert job.status == "DONE"
    assert version.status == "ACTIVE"
    assert version.metrics["macro_f1"] == 1.0
    assert version.supported_classes == ml.CODES[:2]
    assert digest_file(Path(version.model_path)) == version.model_sha256
    assert not ml.schedule_training()  # Identical labels do not produce endless retraining.
    photo = db.scalar(select(Photo).order_by(Photo.id))
    result = ml.LocalClassifier().classify(media_path(photo.id, True))
    assert result.classification.work_type == ml.CODES[0]
    assert result.raw["provider"] == "local" and result.raw["model_id"] == version.id
    ml.load_model.cache_clear()


def test_learning_api_requires_admin_and_data(admin):
    response = admin.get("/api/ml")
    assert response.status_code == 200 and response.json()["active"] is None
    assert admin.post("/api/ml/train").status_code == 409
    admin.post("/api/auth/logout")
    admin.post("/api/auth/login", json={"login": "operator", "password": "test-password-123"})
    admin.headers["X-CSRF-Token"] = admin.cookies["csrf"]
    assert admin.get("/api/ml").status_code == 403
    assert admin.post("/api/ml/train").status_code == 403


def test_training_can_resume_after_labels_are_removed_then_restored(db, monkeypatch):
    from app.worker import run_once

    small_training_config(monkeypatch)
    seed_dataset(db)
    assert ml.schedule_training()
    photos = list(db.scalars(select(Photo)))
    for photo in photos:
        photo.work_type_source = "AI"
    db.commit()
    assert run_once(kinds=["TRAIN"])
    assert db.scalar(select(ModelVersion)) is None
    for photo in photos:
        photo.work_type_source = "OPERATOR"
    db.commit()
    assert ml.schedule_training()
    pending = list(db.scalars(select(Job).where(Job.status == "PENDING")))
    assert len(pending) == 1
