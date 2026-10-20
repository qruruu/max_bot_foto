"""A mode switch changes the workspace, never the stored origin of a photo."""
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy import select
from test_chat_access import AccessSession, actor
from test_chat_access import access_api as access_api

from app.models import DayPhotoReview, ExchangeState, Photo


@pytest.mark.parametrize("mode,expected", [("production", 10), ("test", 50)])
def test_all_operator_views_use_the_same_mode_and_chat_scope(access_api, mode, expected):
    client, engine = access_api
    with AccessSession(engine) as db:
        db.get(Photo, 50).cohort = "test"
        db.get(Photo, 20).cohort = "test"  # Another operator's chat stays inaccessible.
        db.get(ExchangeState, 1).intake_cohort = mode
        db.commit()
    assert client.get('/api/meta').json()['intake_cohort'] == mode
    # An invented query parameter cannot override the server's active mode.
    params = {'cohort': 'test' if mode == 'production' else 'production'}
    photos = client.get('/api/photos', params=params).json()
    assert photos['total'] == 1 and [p['id'] for p in photos['items']] == [expected]
    assert client.get('/api/photos/arrivals').json()['photo_ids'] == [expected]
    assert client.get('/api/reports').json()['total'] == 1
    mapped = client.get('/api/photos/map').json()
    assert mapped['summary']['total'] == 1 and [p['id'] for p in mapped['items']] == [expected]
    assert client.get('/api/photos/filter-counts').json()['work_type']['total'] == 1
    summary = client.get('/api/day-reviews/2026-10-18').json()
    assert (summary['total'], summary['ai_pending'], summary['cohort']) == (1, 1, mode)
    book = load_workbook(BytesIO(client.get('/api/export.xlsx').content))
    assert [row[0] for row in list(book['Все фото'].values)[1:]] == [expected]
    assert client.get(f'/api/photos/{expected}/next').json()['id'] is None


@pytest.mark.parametrize('suffix', ['', '/preview', '/original', '/next'])
def test_saved_links_cannot_open_a_photo_from_the_other_mode(access_api, suffix):
    client, engine = access_api
    with AccessSession(engine) as db:
        db.get(Photo, 50).cohort = 'test'
        db.commit()
    assert client.get('/api/photos/50' + suffix).status_code == 404
    assert client.patch('/api/photos/50', json={'version': 1, 'is_defect': True}).status_code == 404


def test_mode_switch_preserves_origins_and_invalidates_an_open_closing_dialog(access_api):
    client, engine = access_api
    actor(client, 1)
    with AccessSession(engine) as db:
        db.get(Photo, 50).cohort = 'test'
        db.commit()
    token = client.get('/api/day-reviews/2026-10-18').json()['snapshot']
    switched = client.put('/api/exchange/mode', json={'cohort': 'test'})
    assert switched.status_code == 200, switched.text
    assert client.post('/api/day-reviews/2026-10-18/close', json={'snapshot': token}).status_code == 409
    with AccessSession(engine) as db:
        assert db.get(Photo, 10).cohort == 'production' and db.get(Photo, 50).cohort == 'test'
        assert not list(db.scalars(select(DayPhotoReview)))
    summary = client.get('/api/day-reviews/2026-10-18').json()
    assert client.post('/api/day-reviews/2026-10-18/close', json={'snapshot': summary['snapshot']}).json()['confirmed'] == 1
    with AccessSession(engine) as db:
        assert [r.photo_id for r in db.scalars(select(DayPhotoReview))] == [50]
        db.get(ExchangeState, 1).intake_cohort = 'production'
        db.commit()
    summary = client.get('/api/day-reviews/2026-10-18').json()
    assert not summary['closed_before'] and summary['confirmed'] == 0
