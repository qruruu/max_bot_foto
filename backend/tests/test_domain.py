from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.catalog import WORK_TYPES, Status
from app.domain import bot_reply, safe_component, storage_path
from app.recognition import Classification
from app.schemas import PhotoEdit, validate_polygon


def photo(**kwargs):
    return SimpleNamespace(
        **{
            "id": 3,
            "status": Status.NEEDS_REVIEW,
            "is_spam": False,
            "district_id": None,
            "work_type": None,
            "review_reason": [],
            "photo_date": date(2026, 10, 1),
            "chat_name": "Чат 1",
            "extension": ".jpg",
            **kwargs,
        }
    )


def test_catalog_matches_short_markings_in_sheet_order():
    markings = [
        "ПГМ", "ПОДХОДЫ", "УРНЫ", "МУСОР_ГАЗОН", "КОЛОДЦЫ", "АРМАТУРА", "ПЛОЩАДКИ", "СЛУЧ_МУСОР",
        "ПОДМЕТАНИЕ", "МОЙКА_УРН", "ГРАБЛИ", "ГАЗОН", "ПОКОС", "БРУСЧ_МОЙКА", "МЕХ_СНЕГ", "ВЫВОЗ_СНЕГА",
    ]
    assert list(WORK_TYPES.values()) == [(label, label) for label in markings]


@pytest.mark.parametrize(
    "status,text",
    [
        (Status.FORWARDED, "❌ Не принято: пересланные фотографии не принимаются."),
        (Status.DUPLICATE, "❌ Не принято: фотография уже была отправлена."),
        (Status.NEEDS_REVIEW, "✅ Принято"),
        (Status.REJECTED, "❌ Не принято: файл изображения повреждён или не читается."),
    ],
)
def test_exact_replies(status, text):
    assert bot_reply([photo(status=status)], {}) == text


def test_reply_hides_review_and_no_work_without_district():
    assert bot_reply([photo(work_type="BIN_EMPTYING")], {}) == "✅ Принято"
    assert bot_reply([photo(district_id=1)], {1: "12 мкр"}) == "✅ Принято\nМикрорайон: 12 мкр"
    assert (
        bot_reply([photo(district_id=1, work_type="BIN_EMPTYING")], {1: "12 мкр"})
        == "✅ Принято\nМикрорайон: 12 мкр\nВид работы: УРНЫ"
    )
    assert (
        bot_reply([photo(), photo(status=Status.DUPLICATE)], {})
        == "✅ Обработано фотографий: 2\nПринято: 1\nНе принято: 1"
    )


def test_storage_paths_and_sanitization():
    p = photo()
    assert storage_path(p, None) == (
        "disk:/MAX_PHOTOS/2026-10-01/Чат_1/МР_НЕ_ОПРЕДЕЛЕН/МР_НЕ_ОПРЕДЕЛЕН_НЕ_ОПРЕДЕЛЕНО_3.jpg"
    )
    assert storage_path(photo(work_type="BIN_EMPTYING"), "12 мкр") == (
        "disk:/MAX_PHOTOS/2026-10-01/Чат_1/12_мкр/12_мкр_УРНЫ_3.jpg"
    )
    assert storage_path(photo(is_spam=True), "12 мкр") == (
        "disk:/MAX_PHOTOS/СПАМ/2026-10-01/Чат_1/12_мкр/Спам_3.jpg"
    )
    p.photo_date = None
    assert "ДАТА_НЕ_ОПРЕДЕЛЕНА" in storage_path(p, None)
    assert "/" not in safe_component("../../abc/def")
    assert (
        len(storage_path(photo(work_type="PLAYGROUND_MAINTENANCE"), "x" * 500).split("/")[-1].encode()) <= 255
    )


def test_classifier_validation_and_threshold():
    c = Classification(result="SINGLE", work_type="BIN_EMPTYING", confidence=0.8, alternatives=[])
    assert c.automatic_work_type(0.8) == "BIN_EMPTYING"
    assert c.automatic_work_type(0.81) is None
    multiple = Classification(
        result="MULTIPLE", work_type=None, confidence=0.9, alternatives=["BIN_EMPTYING", "SWEEPING"]
    )
    assert multiple.automatic_work_type(0.8) is None


@pytest.mark.parametrize(
    "update",
    [
        {"work_type": "invented"},
        {"confidence": float("nan")},
        {"confidence": 1.1},
        {"alternatives": ["invented"]},
        {"result": "UNKNOWN"},
    ],
)
def test_invalid_classifier_output(update):
    with pytest.raises(ValidationError):
        Classification.model_validate(
            {"result": "SINGLE", "work_type": "BIN_EMPTYING", "confidence": 0.9, "alternatives": [], **update}
        )


def test_review_requires_coordinate_pair_and_catalog():
    with pytest.raises(ValidationError):
        PhotoEdit(version=1, latitude=61)
    with pytest.raises(ValidationError):
        PhotoEdit(version=1, work_type="OTHER")
    with pytest.raises(ValidationError):
        PhotoEdit(version=1, latitude=91, longitude=70)
    assert PhotoEdit(version=1, latitude=None, longitude=None).latitude is None


def test_polygon_validation():
    assert (
        validate_polygon(
            {"type": "Polygon", "coordinates": [[[72, 61], [73, 61], [73, 62], [72, 62], [72, 61]]]}
        ).geom_type
        == "MultiPolygon"
    )
    with pytest.raises(ValueError):
        validate_polygon({"type": "Point", "coordinates": [72, 61]})
    with pytest.raises(ValueError):
        validate_polygon(
            {"type": "Polygon", "coordinates": [[[72, 61], [73, 62], [73, 61], [72, 62], [72, 61]]]}
        )
