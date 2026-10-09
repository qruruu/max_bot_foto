"""Local ResNet-18 classifier and supervised continual training. No hosted inference APIs."""

import hashlib
import json
import logging
import os
import secrets
import time
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageOps
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.catalog import WORK_TYPES
from app.config import settings
from app.db import engine
from app.domain import audit, enqueue, now
from app.media import analysis_image, digest_file, media_path
from app.models import Job, ModelVersion, Photo
from app.recognition import Classification, ClassificationResponse

log = logging.getLogger(__name__)
CODES = list(WORK_TYPES)
ARCHITECTURE = "resnet18-local-v2-short16"
BACKBONE_URL = "https://download.pytorch.org/models/resnet18-f37072fd.pth"


@dataclass(frozen=True)
class Example:
    photo_id: int
    sha256: str
    label: str
    path: Path

    @property
    def validation(self):
        # Stable assignment independent of label/count/version. A holdout never enters training.
        return int(hashlib.sha256(("holdout-v1:" + self.sha256).encode()).hexdigest()[:8], 16) % 5 == 0


def snapshot(examples: list[Example]) -> dict:
    return {
        str(e.photo_id): {"sha256": e.sha256, "label": e.label}
        for e in sorted(examples, key=lambda e: e.photo_id)
    }


def fingerprint(labels: dict) -> str:
    return hashlib.sha256(json.dumps(labels, sort_keys=True).encode()).hexdigest()


def changed_labels(current: dict, previous: dict) -> int:
    return sum(current.get(k) != previous.get(k) for k in set(current) | set(previous))


def collect_examples(db: Session) -> tuple[list[Example], int]:
    rows = db.execute(
        select(Photo.id, Photo.sha256, Photo.work_type).where(
            Photo.work_type_source == "OPERATOR",
            Photo.is_spam.is_(False),
            Photo.reviewed_by.is_not(None),
            Photo.sha256.is_not(None),
            Photo.work_type.is_not(None),
            Photo.analyzed_at.is_not(None),
            Photo.status.in_(["ACCEPTED", "NEEDS_REVIEW", "ERROR"]),
        )
    )
    examples, missing = [], 0
    for photo_id, sha256, label in rows:
        path = media_path(photo_id, preview=True)
        if label not in WORK_TYPES or not path.is_file():
            missing += 1
            continue
        examples.append(Example(photo_id, sha256, label, path))
    return examples, missing


def training_plan(examples: list[Example]) -> dict:
    cfg = settings()
    totals = Counter(e.label for e in examples)
    validation = Counter(e.label for e in examples if e.validation)
    eligible = [
        code
        for code in CODES
        if totals[code] >= cfg.ml_min_per_class
        and validation[code] >= cfg.ml_min_validation_per_class
        and totals[code] - validation[code] >= 2
    ]
    used = [e for e in examples if e.label in eligible]
    reasons = []
    if len(used) < cfg.ml_min_samples:
        reasons.append(
            f"Нужно минимум {cfg.ml_min_samples} размеченных фото в подготовленных категориях; сейчас {len(used)}"
        )
    if len(eligible) < cfg.ml_min_classes:
        reasons.append(
            f"Нужно минимум {cfg.ml_min_classes} категории с {cfg.ml_min_per_class} фото и отдельной проверочной выборкой"
        )
    return {
        "ready": not reasons,
        "reasons": reasons,
        "eligible_classes": eligible,
        "sample_count": len(used),
        "train_count": sum(not e.validation for e in used),
        "validation_count": sum(e.validation for e in used),
        "classes": [
            {
                "code": c,
                "name": WORK_TYPES[c][0],
                "labeled": totals[c],
                "validation": validation[c],
                "eligible": c in eligible,
            }
            for c in CODES
        ],
    }


def latest_evaluated(db):
    return db.scalar(
        select(ModelVersion)
        .where(
            ModelVersion.status.in_(["ACTIVE", "SUPERSEDED", "REJECTED"]),
            ModelVersion.metrics["architecture"].as_string() == ARCHITECTURE,
        )
        .order_by(ModelVersion.id.desc())
        .limit(1)
    )


def version_dict(version):
    if not version:
        return None
    return {
        key: getattr(version, key)
        for key in [
            "id",
            "status",
            "created_at",
            "finished_at",
            "sample_count",
            "metrics",
            "supported_classes",
            "last_error",
        ]
    }


def active_model(db):
    return db.scalar(
        select(ModelVersion).where(
            ModelVersion.status == "ACTIVE",
            ModelVersion.metrics["architecture"].as_string() == ARCHITECTURE,
        )
    )


def training_status(db: Session):
    examples, missing = collect_examples(db)
    previous = latest_evaluated(db)
    return {
        "provider": "local",
        "architecture": ARCHITECTURE,
        "auto_train": settings().ml_auto_train,
        "labeled_total": len(examples),
        "missing_images": missing,
        "plan": training_plan(examples),
        "new_labels": changed_labels(snapshot(examples), previous.labels_snapshot if previous else {}),
        "min_new_labels": settings().ml_min_new_labels,
        "active": version_dict(active_model(db)),
        "runs": [
            version_dict(v)
            for v in db.scalars(select(ModelVersion).order_by(ModelVersion.id.desc()).limit(15))
        ],
        "queued": db.scalar(select(Job.id).where(Job.kind == "TRAIN", Job.status != "DONE").limit(1))
        is not None,
    }


def schedule_training() -> bool:
    if not settings().ml_auto_train:
        return False
    with Session(engine()) as db:
        db.execute(text("SELECT pg_advisory_xact_lock(7006, 1)"))
        if db.scalar(select(Job.id).where(Job.kind == "TRAIN", Job.status != "DONE").limit(1)):
            return False
        examples, _ = collect_examples(db)
        labels = snapshot(examples)
        previous = latest_evaluated(db)
        if not training_plan(examples)["ready"] or (
            previous and changed_labels(labels, previous.labels_snapshot) < settings().ml_min_new_labels
        ):
            return False
        # The lock and pending-job check deduplicate live requests. A completed job must not
        # prevent this dataset from being retried if labels changed and were later restored.
        enqueue(db, "TRAIN", 0, "train:auto:" + fingerprint(labels) + ":" + secrets.token_hex(8))
        db.commit()
        return True


def torch_modules():
    # Import lazily: login, OCR and untrained-model handling don't need to initialize PyTorch.
    import torch
    from torchvision import models, transforms

    torch.set_num_threads(settings().ml_threads)
    return torch, models, transforms


def prepare_backbone() -> Path:
    cfg = settings()
    path = cfg.ml_backbone_path or cfg.data_dir / "models" / "resnet18-f37072fd.pth"
    if path.is_file():
        if not digest_file(path).startswith("f37072fd"):
            raise RuntimeError("BACKBONE_CHECKSUM_MISMATCH")
        return path
    if not cfg.ml_download_backbone:
        raise RuntimeError("BACKBONE_MISSING")
    import httpx

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".part")
    try:
        # Downloads generic public weights only. No photo, label or account data leaves the server.
        with httpx.stream("GET", BACKBONE_URL, timeout=120, follow_redirects=True) as response:
            response.raise_for_status()
            size = 0
            with temp.open("wb") as out:
                for chunk in response.iter_bytes(256 * 1024):
                    size += len(chunk)
                    if size > 60_000_000:
                        raise RuntimeError("BACKBONE_TOO_LARGE")
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
        if not digest_file(temp).startswith("f37072fd"):
            raise RuntimeError("BACKBONE_CHECKSUM_MISMATCH")
        os.replace(temp, path)
        return path
    finally:
        temp.unlink(missing_ok=True)


def network(backbone: Path | None = None):
    torch, models, _ = torch_modules()
    model = models.resnet18(weights=None)
    if backbone:
        model.load_state_dict(torch.load(backbone, map_location="cpu", weights_only=True))
    model.fc = torch.nn.Linear(model.fc.in_features, len(CODES))
    return model


def transform_image(image: Image.Image):
    _, _, transforms = torch_modules()
    # Resize whole image with letterboxing: work near an edge must not be cropped out.
    image = ImageOps.pad(image.convert("RGB"), (224, 224), color=(128, 128, 128))
    return transforms.Compose(
        [transforms.ToTensor(), transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])]
    )(image)


def metrics_for(truth: list[int], predicted: list[int], classes: list[str]) -> dict:
    rows, f1s = {}, []
    for code in classes:
        idx = CODES.index(code)
        tp = sum(t == idx and p == idx for t, p in zip(truth, predicted, strict=True))
        support = truth.count(idx)
        predicted_count = predicted.count(idx)
        precision = tp / predicted_count if predicted_count else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1s.append(f1)
        rows[code] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
            "predicted_count": predicted_count,
        }
    return {
        "macro_f1": sum(f1s) / len(f1s) if f1s else 0.0,
        "accuracy": sum(t == p for t, p in zip(truth, predicted, strict=True)) / len(truth) if truth else 0.0,
        "per_class": rows,
        "validation_count": len(truth),
    }


def evaluate(model, examples: list[Example], classes: list[str]) -> dict:
    torch, _, _ = torch_modules()
    predictions, truth = [], []
    model.eval()
    with torch.inference_mode():
        for start in range(0, len(examples), settings().ml_batch_size):
            batch = examples[start : start + settings().ml_batch_size]
            images = torch.stack([transform_image(analysis_image(e.path)) for e in batch])
            predictions.extend(model(images).argmax(dim=1).tolist())
            truth.extend(CODES.index(e.label) for e in batch)
    return metrics_for(truth, predictions, classes)


def supported_classes(metrics: dict) -> list[str]:
    cfg = settings()
    return [
        code
        for code, values in metrics["per_class"].items()
        if values["precision"] >= cfg.ml_min_class_precision
        and values["support"] >= cfg.ml_min_validation_per_class
        and values["recall"] >= 0.5
    ]


def promotion_allowed(
    candidate_metrics: dict, supported: list[str], current_metrics: dict | None, current_supported: list[str]
) -> bool:
    if candidate_metrics["macro_f1"] < settings().ml_min_macro_f1 or not supported:
        return False
    if not set(current_supported).issubset(supported):
        return False
    if current_metrics and candidate_metrics["macro_f1"] < current_metrics["macro_f1"]:
        return False
    return True


@lru_cache(maxsize=2)
def load_model(path: str, checksum: str):
    if digest_file(Path(path)) != checksum:
        raise RuntimeError("MODEL_CHECKSUM_MISMATCH")
    torch, _, _ = torch_modules()
    model = network()
    model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
    model.eval()
    return model


def interpret_probabilities(probabilities: list[list[float]], supported: list[str], threshold: float):
    confident = set()
    for row in probabilities:
        ranked = sorted(range(len(row)), key=lambda i: row[i], reverse=True)
        if (
            CODES[ranked[0]] in supported
            and row[ranked[0]] >= threshold
            and row[ranked[0]] - row[ranked[1]] >= 0.15
        ):
            confident.add(CODES[ranked[0]])
    full = probabilities[0]
    ranked = sorted(range(len(full)), key=lambda i: full[i], reverse=True)
    top, second = ranked[:2]
    confidence = float(full[top])
    if len(confident) > 1:
        return Classification(
            result="MULTIPLE", work_type=None, confidence=confidence, alternatives=sorted(confident)
        )
    if CODES[top] in supported and confidence >= threshold and full[top] - full[second] >= 0.15:
        return Classification(result="SINGLE", work_type=CODES[top], confidence=confidence, alternatives=[])
    return Classification(result="UNKNOWN", work_type=None, confidence=confidence, alternatives=[])


class LocalClassifier:
    def classify(self, path: Path) -> ClassificationResponse:
        with Session(engine()) as db:
            active = active_model(db)
            if not active:
                result = Classification(result="UNKNOWN", work_type=None, confidence=0, alternatives=[])
                return ClassificationResponse(
                    result, {"provider": "local", "reason": "MODEL_NOT_TRAINED", "model_id": None}
                )
            model_id, model_path, checksum, supported = (
                active.id,
                active.model_path,
                active.model_sha256,
                active.supported_classes,
            )
        model = load_model(model_path, checksum)
        torch, _, _ = torch_modules()
        image = analysis_image(path)
        w, h = image.size
        crops = [image] + [
            image.crop(box)
            for box in [
                (0, 0, w * 0.7, h * 0.7),
                (w * 0.3, 0, w, h * 0.7),
                (0, h * 0.3, w * 0.7, h),
                (w * 0.3, h * 0.3, w, h),
            ]
        ]
        with torch.inference_mode():
            probabilities = model(torch.stack([transform_image(c) for c in crops])).softmax(dim=1).tolist()
        result = interpret_probabilities(probabilities, supported, settings().work_type_confidence_threshold)
        return ClassificationResponse(
            result,
            {
                "provider": "local",
                "architecture": ARCHITECTURE,
                "model_id": model_id,
                "supported_classes": supported,
                "probabilities": dict(zip(CODES, probabilities[0], strict=True)),
                "crop_predictions": [
                    CODES[max(range(len(row)), key=lambda i: row[i])] for row in probabilities
                ],
            },
        )


def train_model(force: bool = False):
    with engine().connect() as lock:
        if not lock.scalar(text("SELECT pg_try_advisory_lock(7005, 1)")):
            lock.commit()
            raise RuntimeError("TRAINER_BUSY")
        lock.commit()
        run_id = None
        try:
            with Session(engine(), expire_on_commit=False) as db:
                # A crashed training process cannot leave a permanently running version.
                db.execute(
                    update(ModelVersion)
                    .where(ModelVersion.status == "TRAINING")
                    .values(status="INTERRUPTED", finished_at=now())
                )
                examples, _ = collect_examples(db)
                plan = training_plan(examples)
                previous = latest_evaluated(db)
                labels = snapshot(examples)
                if not plan["ready"] or (
                    not force
                    and previous
                    and changed_labels(labels, previous.labels_snapshot) < settings().ml_min_new_labels
                ):
                    db.commit()
                    return
                active = active_model(db)
                active_info = (
                    (active.model_path, active.model_sha256, list(active.supported_classes))
                    if active
                    else None
                )
                run = ModelVersion(
                    status="TRAINING",
                    dataset_fingerprint=fingerprint(labels),
                    sample_count=plan["sample_count"],
                    labels_snapshot=labels,
                    metrics={"architecture": ARCHITECTURE},
                    supported_classes=[],
                )
                db.add(run)
                db.flush()
                run_id = run.id
                db.commit()
            cfg = settings()
            torch, _, _ = torch_modules()
            torch.manual_seed(42)
            model = network(prepare_backbone())
            # Train against the full accumulated dataset, not just recent labels; avoids forgetting.
            for name, param in model.named_parameters():
                param.requires_grad = name.startswith(("layer4.", "fc."))
            train = [e for e in examples if e.label in plan["eligible_classes"] and not e.validation]
            validation = [e for e in examples if e.label in plan["eligible_classes"] and e.validation]
            targets = torch.tensor([CODES.index(e.label) for e in train], dtype=torch.long)
            weights = torch.ones(len(CODES))
            counts = Counter(e.label for e in train)
            for code, count in counts.items():
                weights[CODES.index(code)] = len(train) / (len(counts) * count)
            loss_fn = torch.nn.CrossEntropyLoss(weight=weights)
            optimizer = torch.optim.AdamW(
                [p for p in model.parameters() if p.requires_grad], lr=cfg.ml_learning_rate
            )
            for epoch in range(cfg.ml_epochs):
                # Keep BatchNorm statistics from the backbone stable on small/operator datasets.
                model.eval()
                order = torch.randperm(len(train)).tolist()
                for start in range(0, len(order), cfg.ml_batch_size):
                    indices = order[start : start + cfg.ml_batch_size]
                    batch = torch.stack(
                        [
                            transform_image(ImageOps.mirror(analysis_image(train[i].path)))
                            if torch.rand(()).item() < 0.5
                            else transform_image(analysis_image(train[i].path))
                            for i in indices
                        ]
                    )
                    optimizer.zero_grad(set_to_none=True)
                    loss = loss_fn(model(batch), targets[indices])
                    loss.backward()
                    optimizer.step()
                with Session(engine()) as db:
                    progress = db.get(ModelVersion, run_id)
                    progress.metrics = {
                        "architecture": ARCHITECTURE,
                        "epoch": epoch + 1,
                        "epochs": cfg.ml_epochs,
                    }
                    db.commit()
            metrics = evaluate(model, validation, plan["eligible_classes"])
            supported = supported_classes(metrics)
            incumbent = (
                evaluate(load_model(active_info[0], active_info[1]), validation, plan["eligible_classes"])
                if active_info
                else None
            )
            promote = promotion_allowed(metrics, supported, incumbent, active_info[2] if active_info else [])
            destination = cfg.data_dir / "models" / f"version-{run_id}"
            destination.mkdir(parents=True, exist_ok=True)
            path = destination / "weights.pt"
            temp = path.with_suffix(".tmp")
            torch.save(model.state_dict(), temp)
            with temp.open("rb") as file:
                os.fsync(file.fileno())
            os.replace(temp, path)
            checksum = digest_file(path)
            metrics.update(
                architecture=ARCHITECTURE,
                epochs=cfg.ml_epochs,
                train_count=len(train),
                incumbent_macro_f1=incumbent["macro_f1"] if incumbent else None,
                auto_classification_enabled_for=supported,
            )
            # Don't activate a model trained from labels changed/deleted while this run was computing.
            with Session(engine()) as db:
                fresh, _ = collect_examples(db)
                fresh_labels = snapshot(fresh)
                corrected = any(fresh_labels.get(k) != v for k, v in labels.items())
                if corrected:
                    promote = False
                    metrics["labels_changed_during_training"] = True
                if promote:
                    db.execute(
                        update(ModelVersion)
                        .where(ModelVersion.status == "ACTIVE")
                        .values(status="SUPERSEDED")
                    )
                    db.flush()
                run = db.get(ModelVersion, run_id)
                run.status = "ACTIVE" if promote else "REJECTED"
                run.model_path = str(path)
                run.model_sha256 = checksum
                run.metrics = metrics
                run.supported_classes = supported
                run.finished_at = now()
                audit(
                    db,
                    None,
                    "MODEL_ACTIVATED" if promote else "MODEL_EVALUATED",
                    "model",
                    run_id,
                    None,
                    {"status": run.status, "metrics": metrics, "fingerprint": run.dataset_fingerprint},
                )
                db.commit()
        except Exception as exc:
            if run_id:
                with Session(engine()) as db:
                    run = db.get(ModelVersion, run_id)
                    run.status = "ERROR"
                    run.last_error = type(exc).__name__
                    run.finished_at = now()
                    db.commit()
            raise
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(7005, 1)"))
            lock.commit()


def main():
    import signal

    from app.worker import run_once

    logging.basicConfig(level=logging.INFO)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    next_check = 0.0
    while not stopping:
        try:
            if time.monotonic() >= next_check:
                schedule_training()
                next_check = time.monotonic() + settings().ml_check_seconds
            if not run_once(kinds=["TRAIN"]):
                time.sleep(2)
        except Exception as exc:
            log.warning("trainer_error=%s", type(exc).__name__)
            time.sleep(5)


if __name__ == "__main__":
    main()
