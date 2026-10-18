from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import Column, MetaData, Table, create_engine
from sqlalchemy.orm import Session

from app.api import next_photo, photos
from app.catalog import WORK_TYPE_DISPLAY_ORDER, WORK_TYPES
from app.models import Photo, WorkType
from app.reports import photo_list_position
from app.schemas import PhotoFilters, PhotoListFilters


@pytest.fixture
def archive():
    # Execute the actual navigation/filter SQL without requiring PostGIS geometry.
    columns = (
        "id", "received_at", "preview_removed_at", "is_spam", "photo_date",
        "max_chat_id", "district_id", "work_type", "status", "reviewed_by",
    )
    table = Table("photos", MetaData(), *(
        Column(name, Photo.__table__.c[name].type, primary_key=name == "id") for name in columns
    ))
    engine = create_engine("sqlite://")
    table.metadata.create_all(engine)
    WorkType.__table__.create(engine)
    records = {}
    with Session(engine) as session:
        session.add_all([WorkType(code=code, name=names[0], filename_label=names[1],
                                   model_index=i, sort_order=WORK_TYPE_DISPLAY_ORDER.index(code)+1)
                         for i, (code, names) in enumerate(WORK_TYPES.items())])
        session.flush()
        db = Mock()
        db.scalar.side_effect = session.scalar
        db.get.side_effect = lambda model, key: records.get(key)

        def add(id, **values):
            fields = dict(
                id=id, received_at=datetime(2026, 10, 17, 12), preview_removed_at=None,
                is_spam=False, photo_date=None, max_chat_id=123, district_id=None,
                work_type="BIN_EMPTYING", status="ACCEPTED", reviewed_by=None,
            )
            fields.update(values)
            session.execute(table.insert().values(**fields))
            records[id] = Photo(**fields)
            return records[id]

        def next_id(id, user=None, **filters):
            return next_photo(
                id, db, user or SimpleNamespace(role="ADMIN_OPERATOR"), PhotoFilters(**filters),
            )["id"]

        def position(id=None, **filters):
            from app.reports import filtered

            selection = PhotoListFilters(**filters)
            total = len(session.scalars(filtered(selection).with_only_columns(Photo.id)).all())
            return photo_list_position(db, selection, total, records.get(id))

        yield SimpleNamespace(add=add, next=next_id, position=position, db=db, records=records)
    engine.dispose()


def test_archive_advances_in_list_order_including_equal_timestamps_and_end(archive):
    archive.add(10)
    archive.add(20)
    archive.add(30)
    archive.add(99, received_at=datetime(2026, 10, 16))
    assert archive.next(30, status="ACCEPTED", page=20, page_size=1) == 20
    assert archive.next(20, status="ACCEPTED") == 10
    assert archive.next(10, status="ACCEPTED") == 99
    assert archive.next(99, status="ACCEPTED") is None


def test_next_photo_keeps_filters_and_excludes_spam_and_removed_previews(archive):
    archive.add(100)
    archive.add(90, status="NEEDS_REVIEW")
    archive.add(80, max_chat_id=999)
    archive.add(70, district_id=5)
    archive.add(60, work_type="SWEEPING")
    archive.add(50, reviewed_by=2)
    archive.add(40, is_spam=True)
    archive.add(30, preview_removed_at=datetime(2026, 10, 17))
    archive.add(20)
    assert archive.next(
        100, status="ACCEPTED", chat_id=123, district_id=0,
        work_type="BIN_EMPTYING", operator_id=0,
    ) == 20


def test_next_photo_uses_immutable_position_even_after_current_leaves_filters(archive):
    current = archive.add(30, work_type="SWEEPING")
    archive.add(20)
    archive.add(10)
    # Saving a category/date/status correction must not restart the list.
    assert current.work_type != "BIN_EMPTYING"
    assert archive.next(30, work_type="BIN_EMPTYING") == 20


def test_review_visits_remaining_rows_before_revisiting_an_unresolved_photo(archive):
    for id in [50,40,30,20,10]:
        archive.add(id,status="NEEDS_REVIEW")
    # 50 is left uncertain; saving 40 must still advance to 30, not back to 50.
    assert archive.next(50,status="NEEDS_REVIEW") == 40
    assert archive.next(40,status="NEEDS_REVIEW") == 30
    assert archive.next(30,status="NEEDS_REVIEW") == 20
    assert archive.next(20,status="NEEDS_REVIEW") == 10
    assert archive.next(10,status="NEEDS_REVIEW") == 50


def test_review_wrap_keeps_filters_and_excludes_accepted_spam_removed_and_current(archive):
    archive.add(100,status="ACCEPTED")
    archive.add(90,status="NEEDS_REVIEW",max_chat_id=999)
    archive.add(80,status="NEEDS_REVIEW",work_type="SWEEPING")
    archive.add(70,status="NEEDS_REVIEW",district_id=5)
    archive.add(60,status="NEEDS_REVIEW",reviewed_by=2)
    archive.add(50,status="NEEDS_REVIEW",is_spam=True)
    archive.add(40,status="NEEDS_REVIEW",preview_removed_at=datetime(2026,10,17))
    archive.add(30,status="NEEDS_REVIEW")
    archive.add(10,status="NEEDS_REVIEW")
    assert archive.next(10,status="NEEDS_REVIEW",chat_id=123,work_type="BIN_EMPTYING",
                        district_id=0,operator_id=0) == 30


def test_review_with_only_the_current_photo_returns_to_the_list(archive):
    archive.add(30,status="ACCEPTED")
    archive.add(20,status="NEEDS_REVIEW")
    assert archive.next(20,status="NEEDS_REVIEW") is None


def test_review_wrap_uses_the_same_tiebreaker_and_skips_a_saved_photo(archive):
    # Even when the current record no longer matches after a save, the next
    # endpoint uses its immutable position and the remaining review rows.
    archive.add(100,status="NEEDS_REVIEW",received_at=datetime(2026,10,16))
    archive.add(30,status="NEEDS_REVIEW")
    archive.add(20,status="ACCEPTED")
    archive.add(10,status="NEEDS_REVIEW")
    assert archive.next(20,status="NEEDS_REVIEW") == 10
    assert archive.next(100,status="NEEDS_REVIEW") == 30


def test_spam_list_and_access_checks_are_preserved(archive):
    archive.add(30, is_spam=True, status="SPAM")
    archive.add(20)
    archive.add(10, is_spam=True, status="SPAM")
    assert archive.next(30, status="SPAM") == 10
    assert archive.next(10, status="SPAM") is None
    reader = SimpleNamespace(role="OPERATOR", permissions=["photos_view"])
    for source, filters in [(30, {}), (20, {"status": "SPAM"})]:
        with pytest.raises(HTTPException) as error:
            archive.next(source, user=reader, **filters)
        assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        archive.next(20, user=SimpleNamespace(role="OPERATOR", permissions=[]))
    assert error.value.status_code == 403


@pytest.mark.parametrize("removed", [False, True])
def test_unavailable_source_photo_returns_404(archive, removed):
    if removed:
        archive.add(10, preview_removed_at=datetime(2026, 10, 17) - timedelta(hours=1))
    with pytest.raises(HTTPException) as error:
        archive.next(10)
    assert error.value.status_code == 404
    archive.db.scalar.assert_not_called()


def test_return_to_photo_resolves_its_page_and_row_with_equal_timestamps(archive):
    for id in range(1, 76):
        archive.add(id)
    assert archive.position(32, page=1) == (2, 13)
    assert archive.position(15, page=2) == (3, 0)
    assert archive.position(75, page=3) == (1, 0)
    assert archive.position(1, page_size=10) == (8, 4)


def test_return_position_ignores_newer_ids_with_older_received_dates(archive):
    archive.add(10)
    archive.add(20)
    archive.add(99, received_at=datetime(2026, 10, 16))
    assert archive.position(99, page_size=1) == (3, 0)
    assert archive.position(10, page_size=1) == (2, 0)


def test_return_position_keeps_filters_and_adapts_to_new_arrivals(archive):
    archive.add(30)
    archive.add(20)
    archive.add(10)
    assert archive.position(10, work_type="BIN_EMPTYING", page_size=2) == (2, 0)
    archive.add(60, work_type="SWEEPING")
    archive.add(50, is_spam=True)
    archive.add(40, preview_removed_at=datetime(2026, 10, 17))
    assert archive.position(10, work_type="BIN_EMPTYING", page_size=2) == (2, 0)
    archive.add(70)
    archive.add(80)
    assert archive.position(10, work_type="BIN_EMPTYING", page_size=2) == (3, 0)


def test_return_to_photo_no_longer_in_filters_uses_nearest_remaining_row(archive):
    archive.add(50)
    archive.add(40, work_type="SWEEPING")
    archive.add(30)
    archive.add(20)
    archive.add(10, work_type="SWEEPING")
    assert archive.position(40, work_type="BIN_EMPTYING", page_size=2) == (1, 1)
    assert archive.position(10, work_type="BIN_EMPTYING", page_size=2) == (2, 0)


def test_return_to_missing_photo_preserves_page_and_clamps_a_shrunken_list(archive):
    for id in range(1, 36):
        archive.add(id)
    assert archive.position(page=2) == (2, None)
    assert archive.position(page=3) == (2, None)
    assert archive.position(1, status="SPAM", page=2) == (1, None)


@pytest.mark.parametrize("anchor", [
    None,
    Photo(id=99, is_spam=True),
    Photo(id=99, preview_removed_at=datetime(2026, 10, 18)),
])
def test_list_ignores_missing_or_inaccessible_anchor_without_disclosing_its_position(monkeypatch, anchor):
    db = Mock()
    db.get.return_value = anchor
    db.scalar.return_value = 37
    db.scalars.return_value = [Photo(id=7)]
    monkeypatch.setattr("app.api.dictionaries", lambda db: ({}, {}))
    monkeypatch.setattr("app.api.work_catalog", lambda db: {})
    user = SimpleNamespace(role="OPERATOR", permissions=["photos_view"])
    result = photos(db, user, PhotoListFilters(anchor_id=99, page=2))
    assert result["page"] == 2 and result["focus_id"] is None
    assert [photo["id"] for photo in result["items"]] == [7]
    db.scalar.assert_called_once()


def test_list_response_selects_the_resolved_page_and_photo_to_focus(monkeypatch):
    db = Mock()
    db.get.return_value = Photo(id=3, received_at=datetime(2026, 10, 18))
    db.scalar.side_effect = [35, 31]
    db.scalars.return_value = [Photo(id=id) for id in [4, 3, 2, 1]]
    monkeypatch.setattr("app.api.dictionaries", lambda db: ({}, {}))
    monkeypatch.setattr("app.api.work_catalog", lambda db: {})
    result = photos(db, SimpleNamespace(role="ADMIN_OPERATOR"), PhotoListFilters(anchor_id=3))
    assert result["page"] == 2 and result["focus_id"] == 3
