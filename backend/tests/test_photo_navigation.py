from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import Column, MetaData, Table, create_engine
from sqlalchemy.orm import Session

from app.api import next_photo, photos
from app.models import Photo
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
    records = {}
    with Session(engine) as session:
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
    result = photos(db, SimpleNamespace(role="ADMIN_OPERATOR"), PhotoListFilters(anchor_id=3))
    assert result["page"] == 2 and result["focus_id"] == 3
