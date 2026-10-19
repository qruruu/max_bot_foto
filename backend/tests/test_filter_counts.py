from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Table, create_engine, event
from sqlalchemy.orm import Session

from app.api import app
from app.auth import current_user
from app.db import get_db
from app.filter_counts import photo_filter_counts
from app.models import Photo
from app.schemas import PhotoFilters


@pytest.fixture
def count_db():
    names = (
        "id", "received_at", "preview_removed_at", "is_spam", "photo_date",
        "max_chat_id", "district_id", "work_type", "status", "reviewed_by", "sender_id",
    )
    table = Table("photos", MetaData(), *(
        Column(name, Photo.__table__.c[name].type, primary_key=name == "id") for name in names
    ))
    engine = create_engine("sqlite://")
    # Fixtures have explicit photo dates; register the PostgreSQL fallback's name
    # so SQLite can prepare the shared date-range expression.
    @event.listens_for(engine, "connect")
    def functions(connection, _):
        connection.create_function("timezone", 2, lambda zone, value: value)

    table.metadata.create_all(engine)
    with Session(engine) as db:
        def add(id, **values):
            row = dict(id=id, received_at=datetime(2026, 10, 18), preview_removed_at=None,
                       is_spam=False, photo_date=date(2026, 10, 18), max_chat_id=100,
                       district_id=1, work_type="BIN_EMPTYING", status="ACCEPTED", reviewed_by=10)
            row.update(values)
            db.execute(table.insert().values(**row))

        add(1)
        add(2, work_type="GREEN_CLEANING", status="NEEDS_REVIEW", reviewed_by=None)
        add(3, district_id=2, reviewed_by=11)
        add(4, work_type=None, district_id=None, max_chat_id=200, status="ERROR", reviewed_by=None)
        add(5, work_type="GREEN_CLEANING", district_id=2, max_chat_id=200, status="RECEIVED")
        add(6, status="SPAM", is_spam=True, max_chat_id=200, reviewed_by=11)
        add(7, preview_removed_at=datetime(2026, 10, 18))
        add(8, photo_date=date(2026, 10, 17))
        yield db
    engine.dispose()


def test_counts_cover_the_entire_selection_not_just_a_table_page(count_db):
    result = photo_filter_counts(count_db, PhotoFilters(page=10, page_size=1), include_spam=True)
    assert result["work_type"] == {"total": 6, "values": {"BIN_EMPTYING": 3, "GREEN_CLEANING": 2, "NONE": 1}}
    assert result["district_id"] == {"total": 6, "values": {"1": 3, "2": 2, "0": 1}}
    assert result["chat_id"] == {"total": 6, "values": {"100": 4, "200": 2}}
    assert result["operator_id"] == {"total": 6, "values": {"10": 3, "11": 1, "0": 2}}
    assert result["status"] == {"total": 6, "values": {
        "ACCEPTED": 3, "NEEDS_REVIEW": 1, "RECEIVED": 1, "ERROR": 1, "ACCEPTED_ALL": 4, "SPAM": 1,
    }}


@pytest.mark.parametrize("field,value,facet", [
    ("work_type", "BIN_EMPTYING", "work_type"), ("district_id", 1, "district_id"),
    ("chat_id", 100, "chat_id"), ("operator_id", 10, "operator_id"),
    ("status", "ACCEPTED", "status"), ("accepted_only", True, "status"),
])
def test_each_menu_ignores_its_own_selection_but_keeps_other_filters(count_db, field, value, facet):
    unselected = photo_filter_counts(count_db, PhotoFilters())
    selected = photo_filter_counts(count_db, PhotoFilters(**{field: value}))
    assert selected[facet] == unselected[facet]
    other = "district_id" if facet == "work_type" else "work_type"
    assert selected[other]["total"] < unselected[other]["total"]


def test_date_range_and_combined_filters_apply_to_alternatives(count_db):
    result = photo_filter_counts(count_db, PhotoFilters(
        date_from=date(2026, 10, 18), date_to=date(2026, 10, 18),
        district_id=1, work_type="BIN_EMPTYING",
    ), include_spam=True)
    assert result["work_type"] == {"total": 2, "values": {"BIN_EMPTYING": 1, "GREEN_CLEANING": 1}}
    assert result["district_id"] == {"total": 2, "values": {"1": 1, "2": 1}}
    assert result["chat_id"] == {"total": 1, "values": {"100": 1}}
    assert result["operator_id"] == {"total": 1, "values": {"10": 1}}
    assert result["status"]["total"] == 1
    assert result["status"]["values"]["SPAM"] == 1


def test_unassigned_values_and_empty_results(count_db):
    result = photo_filter_counts(count_db, PhotoFilters(work_type="NONE", district_id=0, operator_id=0))
    assert result["work_type"] == {"total": 1, "values": {"NONE": 1}}
    assert result["district_id"] == {"total": 1, "values": {"0": 1}}
    assert result["operator_id"] == {"total": 1, "values": {"0": 1}}
    assert result["status"]["values"]["ERROR"] == 1
    empty = photo_filter_counts(count_db, PhotoFilters(chat_id=999, district_id=999))
    assert all(facet["total"] == 0 for facet in empty.values())


def test_spam_scope_is_explicit_and_status_totals_do_not_double_count_it(count_db):
    result = photo_filter_counts(count_db, PhotoFilters(status="SPAM"), include_spam=True)
    assert result["work_type"] == {"total": 1, "values": {"BIN_EMPTYING": 1}}
    assert result["district_id"] == {"total": 1, "values": {"1": 1}}
    assert result["chat_id"] == {"total": 1, "values": {"200": 1}}
    assert result["status"]["total"] == 6
    assert result["status"]["values"]["SPAM"] == 1
    hidden = photo_filter_counts(count_db, PhotoFilters())
    assert "SPAM" not in hidden["status"]["values"]


@pytest.fixture
def counts_client(monkeypatch):
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: Mock())
    service = Mock(return_value={})
    monkeypatch.setattr("app.api.photo_filter_counts", service)
    with TestClient(app) as client:
        yield client, service, monkeypatch


def test_counts_require_login_and_browsing_permission(counts_client):
    client, service, monkeypatch = counts_client
    assert client.get("/api/photos/filter-counts").status_code == 401
    monkeypatch.setitem(app.dependency_overrides, current_user, lambda: SimpleNamespace(role="OPERATOR", permissions=[]))
    assert client.get("/api/photos/filter-counts").status_code == 403
    service.assert_not_called()


@pytest.mark.parametrize("permissions", [["photos_view"], ["reports_view"]])
def test_photo_and_report_readers_get_counts_without_spam(counts_client, permissions):
    client, service, monkeypatch = counts_client
    monkeypatch.setitem(app.dependency_overrides, current_user, lambda: SimpleNamespace(role="OPERATOR", permissions=permissions))
    assert client.get("/api/photos/filter-counts?work_type=GREEN_CLEANING").status_code == 200
    assert service.call_args.kwargs["include_spam"] is False
    assert service.call_args.kwargs["user"].permissions == permissions
    assert client.get("/api/photos/filter-counts?status=SPAM").status_code == 403


def test_admin_gets_spam_counts_and_query_validation_still_applies(counts_client):
    client, service, monkeypatch = counts_client
    monkeypatch.setitem(app.dependency_overrides, current_user, lambda: SimpleNamespace(role="ADMIN_OPERATOR"))
    assert client.get("/api/photos/filter-counts").status_code == 200
    assert service.call_args.kwargs["include_spam"] is True
    assert service.call_args.kwargs["user"].role == "ADMIN_OPERATOR"
    assert client.get("/api/photos/filter-counts?date_from=2026-10-18&date_to=2026-10-17").status_code == 422
