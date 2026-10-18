from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api import edit_photo
from app.catalog import WORK_TYPES, Status
from app.domain import now, reassess, storage_path
from app.models import District, Photo
from app.schemas import PhotoEdit


@pytest.fixture
def record():
    return Photo(
        id=7,
        version=1,
        district_id=None,
        district_source=None,
        photo_date=date(2026, 10, 16),
        latitude=None,
        longitude=None,
        work_type="BIN_EMPTYING",
        work_type_source="AI",
        is_spam=False,
        status=Status.NEEDS_REVIEW,
        review_reason=["COORDINATES_MISSING"],
        analyzed_at=now(),
        preview_removed_at=None,
        extension=".jpg",
        cohort="production",
        detected_address="Исходный адрес OCR",
        detected_city="Нефтеюганск",
    )


@pytest.fixture
def session(record, monkeypatch):
    monkeypatch.setattr("app.api.work_catalog", lambda db: WORK_TYPES)
    monkeypatch.setattr("app.api.require_work_type", lambda db, code: None)
    districts = {
        10: District(id=10, name="12 мкр", active=True),
        20: District(id=20, name="11 мкр", active=True),
        30: District(id=30, name="Старый микрорайон", active=False),
    }
    db = Mock()
    db.get.side_effect = lambda model, key: record if model is Photo and key == record.id else (
        districts.get(key) if model is District else None
    )
    db.scalar.return_value = None
    return db


def save(session, record, **values):
    return edit_photo(
        record.id,
        PhotoEdit(version=record.version, **values),
        session,
        SimpleNamespace(id=1, role="ADMIN_OPERATOR"),
    )


@pytest.mark.parametrize("coordinates", [(None, None), (40, 40), (61.1, 72.6)])
def test_manual_district_is_saved_without_changing_coordinates(session, record, monkeypatch, coordinates):
    record.latitude, record.longitude = coordinates
    resolve = Mock(side_effect=AssertionError("Manual district must not be recalculated"))
    monkeypatch.setattr("app.domain.resolve_district", resolve)
    result = save(session, record, district_id=10)
    assert result["status"] == Status.ACCEPTED
    assert result["district_id"] == 10 and result["district_source"] == "OPERATOR"
    assert record.district_name_snapshot == "12 мкр"
    assert (record.latitude, record.longitude) == coordinates
    assert record.review_reason == []
    assert record.storage_status == "PENDING" and record.version == 2
    assert record.detected_address == "Исходный адрес OCR" and record.detected_city == "Нефтеюганск"
    assert storage_path(record, record.district_name_snapshot).endswith("/12_мкр/12_мкр_УРНЫ_7.jpg")
    audit = session.add.call_args.args[0]
    assert audit.old_value["district_id"] is None and audit.old_value["district_source"] is None
    assert audit.new_value["district_id"] == 10 and audit.new_value["district_source"] == "OPERATOR"
    assert audit.new_value["district_name_snapshot"] == "12 мкр"
    session.commit.assert_called_once()
    resolve.assert_not_called()


def test_manual_district_survives_other_edits_reassessment_and_deactivation(session, record):
    save(session, record, district_id=10)
    session.get(District, 10).active = False
    session.get(District, 10).name = "12 микрорайон"
    save(session, record, photo_date="2026-10-17", district_id=10)
    save(session, record, work_type="SWEEPING")
    reassess(session, record)
    assert record.district_id == 10 and record.district_source == "OPERATOR"
    assert record.district_name_snapshot == "12 микрорайон"
    assert record.status == Status.ACCEPTED
    assert record.latitude is record.longitude is None


@pytest.mark.parametrize("district_id", [999, 30])
def test_unknown_or_inactive_district_is_rejected_before_any_changes(session, record, district_id):
    with pytest.raises(HTTPException) as error:
        save(session, record, district_id=district_id, photo_date="2026-10-17")
    assert error.value.status_code == 422
    assert record.district_id is record.district_source is None
    assert record.photo_date == date(2026, 10, 16) and record.version == 1
    session.commit.assert_not_called()


@pytest.mark.parametrize("coordinates,resolved", [((None, None), (None, "COORDINATES_MISSING")),
                                                   ((61.1, 72.6), (20, None))])
def test_explicit_null_returns_to_automatic_district(session, record, monkeypatch, coordinates, resolved):
    save(session, record, district_id=10)
    record.latitude, record.longitude = coordinates
    monkeypatch.setattr("app.domain.resolve_district", lambda *args: resolved)
    save(session, record, district_id=None)
    assert record.district_id == resolved[0]
    assert record.district_source == ("COORDINATES" if resolved[0] else None)
    assert record.review_reason == ([resolved[1]] if resolved[1] else [])
    assert record.status == (Status.NEEDS_REVIEW if resolved[1] else Status.ACCEPTED)


def test_manual_district_does_not_hide_other_review_reasons(session, record):
    record.photo_date, record.work_type = None, None
    save(session, record, district_id=10)
    assert record.status == Status.NEEDS_REVIEW
    assert record.review_reason == ["DATE_MISSING", "WORK_UNCERTAIN"]


def test_spam_and_restoration_keep_manual_district(session, record):
    save(session, record, district_id=10)
    save(session, record, is_spam=True)
    assert record.status == Status.SPAM and record.district_source == "OPERATOR"
    save(session, record, is_spam=False, work_type="BIN_EMPTYING")
    assert record.status == Status.ACCEPTED and record.district_id == 10


def test_stale_version_cannot_change_manual_district(session, record):
    save(session, record, district_id=10)
    with pytest.raises(HTTPException) as error:
        edit_photo(record.id, PhotoEdit(version=1, district_id=20), session,
                   SimpleNamespace(id=1, role="ADMIN_OPERATOR"))
    assert error.value.status_code == 409 and record.district_id == 10


@pytest.mark.parametrize("district_id", [0, -1, 1.5, "unknown"])
def test_district_input_requires_a_real_positive_integer(district_id):
    with pytest.raises(ValidationError):
        PhotoEdit(version=1, district_id=district_id)


def test_district_patch_distinguishes_omission_from_automatic_mode():
    assert "district_id" not in PhotoEdit(version=1).model_dump(exclude_unset=True)
    assert PhotoEdit(version=1, district_id=None).model_dump(exclude_unset=True)["district_id"] is None
