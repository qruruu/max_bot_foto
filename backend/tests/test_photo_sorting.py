"""Normal operator sorting omits auxiliary archives while preserving explicit access."""
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy import select
from test_chat_access import AccessSession, actor
from test_chat_access import access_api as access_api

from app.models import Photo
from app.schemas import PhotoBrowseFilters, PhotoFilters, PhotoListFilters, PhotoMapFilters


@pytest.fixture
def sorting_api(access_api):
    client, engine = access_api
    actor(client,1)
    with AccessSession(engine) as db:
        db.get(Photo,20).status = 'DUPLICATE'
        db.get(Photo,60).status = 'FORWARDED'
        db.get(Photo,50).status = 'NEEDS_REVIEW'
        db.commit()
    return client, engine


def test_normal_list_and_next_skip_duplicates_forwarded_and_spam(sorting_api):
    client, _ = sorting_api
    result = client.get('/api/photos').json()
    assert result['total'] == 2 and [p['id'] for p in result['items']] == [50,10]
    assert client.get('/api/photos?page_size=1&page=2').json()['items'][0]['id'] == 10
    assert client.get('/api/photos/60/next').json() == {'id':50}
    assert client.get('/api/photos/50/next').json() == {'id':10}
    assert client.get('/api/photos/10/next').json() == {'id':None}
    assert client.get('/api/photos/10/next?status=NEEDS_REVIEW').json() == {'id':50}


@pytest.mark.parametrize('status,ids', [('DUPLICATE',{20}),('FORWARDED',{60}),('SPAM',{30,40})])
def test_explicit_status_still_opens_each_separate_archive(sorting_api,status,ids):
    client, _ = sorting_api
    result = client.get('/api/photos?work_only=true&status='+status).json()
    assert {p['id'] for p in result['items']} == ids
    mapped = client.get('/api/photos/map?work_only=true&status='+status).json()
    assert {p['id'] for p in mapped['items']} == ids
    latest = max(ids)
    assert client.get(f'/api/photos/{latest}/next?work_only=true&status='+status).json()['id'] == (min(ids) if len(ids)>1 else None)


def test_map_notifications_and_export_match_the_sorting_list(sorting_api):
    client, _ = sorting_api
    mapped = client.get('/api/photos/map').json()
    assert mapped['summary']['total'] == 2 and {p['id'] for p in mapped['items']} == {10,50}
    assert client.get('/api/photos/arrivals').json()['photo_ids'] == [10,50]
    response = client.get('/api/export.xlsx?work_only=true')
    assert response.status_code == 200
    book = load_workbook(BytesIO(response.content))
    assert {row[0] for row in list(book['Все фото'].values)[1:]} == {10,50}
    assert sum(row[1] for row in list(book['По чатам'].values)[1:]) == 2


def test_filter_counts_match_normal_sorting_and_keep_archived_alternatives_visible(sorting_api):
    client, _ = sorting_api
    counts = client.get('/api/photos/filter-counts?work_only=true').json()
    assert all(counts[facet]['total'] == 2 for facet in counts)
    assert counts['status']['values']['DUPLICATE'] == 1
    assert counts['status']['values']['FORWARDED'] == 1
    assert counts['status']['values']['SPAM'] == 2
    assert counts['status']['values']['ACCEPTED_ALL'] == 2
    selected = client.get('/api/photos/filter-counts?work_only=true&status=DUPLICATE').json()
    assert selected['work_type']['total'] == 1 and selected['status']['total'] == 2
    assert selected['chat_id']['values'] == {'200':1}


def test_overview_keeps_received_counts_and_no_records_are_removed(sorting_api):
    client, engine = sorting_api
    report = client.get('/api/reports').json()
    assert report['total'] == 4
    assert report['counts']['DUPLICATE'] == report['counts']['FORWARDED'] == 1
    assert client.get('/api/photos?work_only=false').json()['total'] == 4
    assert client.get('/api/reports?work_only=true').json()['total'] == 2
    with AccessSession(engine) as db:
        assert set(db.scalars(select(Photo.id))) == {10,20,30,40,50,60}


def test_sorting_scope_does_not_bypass_chat_or_spam_permissions(sorting_api):
    client, engine = sorting_api
    actor(client,2)
    assert client.get('/api/photos?status=DUPLICATE').json()['total'] == 0
    assert client.get('/api/photos?status=FORWARDED').json()['total'] == 0
    from app.models import User
    with AccessSession(engine) as db:
        db.get(User,2).permissions = ['photos_view']
        db.commit()
    assert client.get('/api/photos?work_only=true&status=SPAM').status_code == 403
    assert client.get('/api/photos/map?work_only=true&status=SPAM').status_code == 403


def test_browsing_defaults_are_distinct_from_overview_and_report_filters():
    assert PhotoBrowseFilters().work_only
    assert PhotoListFilters().work_only
    assert PhotoMapFilters().work_only
    assert not PhotoFilters().work_only
    assert not PhotoListFilters(work_only=False).work_only
