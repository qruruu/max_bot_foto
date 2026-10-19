"""Chronological sorting must agree across pages, next, anchors and exported rows."""
from datetime import UTC, date, datetime, time
from io import BytesIO

import pytest
from openpyxl import load_workbook
from test_chat_access import AccessSession, actor
from test_chat_access import access_api as access_api

from app.models import Audit, LoginSession, Photo, User
from app.permissions import DEFAULT_OPERATOR_PERMISSIONS, Permission

ASC_PHOTO = [30,90,20,70,10,50,100,40,80,60]
DESC_PHOTO = [100,40,10,70,20,90,50,30,80,60]
ASC_RECEIVED = [10,20,70,30,40,50,60,80,90,100]
DESC_RECEIVED = list(reversed(ASC_RECEIVED))


@pytest.fixture
def time_api(access_api):
    client, engine = access_api
    actor(client,1)
    records = [
        (10,18,time(14),5), (20,18,time(9),6), (30,17,time(23),7),
        (40,19,None,8), (50,18,None,9), (60,None,None,10),
        (70,18,time(9),6), (80,None,time(8),11), (90,18,time(0),12), (100,19,time(7),13),
    ]
    with AccessSession(engine) as db:
        for id, day, taken, received in records:
            photo = db.get(Photo,id)
            if photo is None:
                photo = Photo(id=id,version=1,cohort='production',max_chat_id=100,chat_name='Тест',
                              max_message_id=str(id),work_type='BIN_EMPTYING',analyzed_at=datetime(2026,10,19,tzinfo=UTC))
                db.add(photo)
            photo.photo_date = date(2026,10,day) if day else None
            photo.photo_time = taken
            photo.received_at = datetime(2026,10,19,received,tzinfo=UTC)
            photo.status, photo.is_spam = 'ACCEPTED', False
            photo.latitude = photo.longitude = None
        db.commit()
    return client, engine


@pytest.mark.parametrize('basis,order,expected', [
    ('photo','asc',ASC_PHOTO), ('photo','desc',DESC_PHOTO),
    ('received','asc',ASC_RECEIVED), ('received','desc',DESC_RECEIVED),
    ('photo','received_desc',DESC_RECEIVED), ('received','received_desc',DESC_RECEIVED),
])
def test_pages_next_return_position_and_excel_use_the_same_time_order(time_api,basis,order,expected):
    client, _ = time_api
    query = f'date_basis={basis}&sort_order={order}'
    seen = []
    for page in range(1,5):
        result = client.get(f'/api/photos?{query}&page_size=3&page={page}')
        assert result.status_code == 200, result.text
        assert result.json()['total'] == len(expected)
        seen.extend(p['id'] for p in result.json()['items'])
    assert seen == expected
    for index, id in enumerate(expected):
        next_id = client.get(f'/api/photos/{id}/next?{query}').json()['id']
        assert next_id == (expected[index+1] if index+1<len(expected) else None)
    returned = client.get(f'/api/photos?{query}&page_size=3&page=1&anchor_id={expected[7]}').json()
    assert returned['page'] == 3 and returned['focus_id'] == expected[7]
    assert [p['id'] for p in returned['items']] == expected[6:9]
    book = load_workbook(BytesIO(client.get('/api/export.xlsx?'+query).content))
    assert [row[0] for row in list(book['Все фото'].values)[1:]] == expected


@pytest.mark.parametrize('order,expected', [('asc',[30,20,10,50]),('desc',[10,20,50,30])])
def test_review_wrap_still_finishes_the_selected_chronological_pass(time_api,order,expected):
    client, engine = time_api
    with AccessSession(engine) as db:
        for id in expected:
            db.get(Photo,id).status = 'NEEDS_REVIEW'
        db.commit()
    for index,id in enumerate(expected):
        result = client.get(f'/api/photos/{id}/next?status=NEEDS_REVIEW&sort_order={order}')
        assert result.status_code == 200
        assert result.json()['id'] == expected[(index+1)%len(expected)]


def test_editing_timestamp_can_move_the_return_anchor_without_resetting_the_next_photo(time_api):
    client, _ = time_api
    # The UI resolves the next ID before saving the edited timestamp.
    assert client.get('/api/photos/20/next?sort_order=asc').json()['id'] == 70
    saved = client.patch('/api/photos/20',json={'version':1,'photo_date':'2026-10-16','photo_time':'10:30:00'})
    assert saved.status_code == 200
    assert client.get('/api/photos/70/next?sort_order=asc').json()['id'] == 10
    returned = client.get('/api/photos?sort_order=asc&anchor_id=20&page_size=3&page=4').json()
    assert returned['page'] == 1 and returned['focus_id'] == 20
    assert returned['items'][0]['id'] == 20


def test_sorting_does_not_change_filter_counts_or_access_scope(time_api):
    client, _ = time_api
    base = client.get('/api/photos/filter-counts?work_only=true').json()
    for order in ['asc','desc']:
        assert client.get('/api/photos/filter-counts?work_only=true&sort_order='+order).json() == base
    actor(client,2)
    response = client.get('/api/photos?sort_order=asc')
    assert response.status_code == 200
    assert {p['max_chat_id'] for p in response.json()['items']} == {'100'}
    assert client.get('/api/photos/20/next?sort_order=asc').status_code == 404


@pytest.mark.parametrize('path', ['/api/photos','/api/photos/10/next','/api/export.xlsx','/api/photos/filter-counts'])
def test_invalid_sort_modes_are_rejected(time_api,path):
    client, _ = time_api
    assert client.get(path+'?sort_order=invalid').status_code == 422


@pytest.mark.parametrize('basis,order', [
    ('photo','asc'), ('photo','desc'), ('received','asc'),
    ('received','desc'), ('photo','received_desc'), ('received','received_desc'),
])
def test_operator_without_sort_permission_cannot_override_order_in_links(time_api,basis,order):
    client, engine = time_api
    with AccessSession(engine) as db:
        db.get(User,4).permissions = list(DEFAULT_OPERATOR_PERMISSIONS)
        db.commit()
    actor(client,4)
    query = f'date_basis={basis}&sort_order={order}'
    result = client.get('/api/photos?'+query).json()
    assert [p['id'] for p in result['items']] == DESC_PHOTO
    for index, id in enumerate(DESC_PHOTO):
        assert client.get(f'/api/photos/{id}/next?{query}').json()['id'] == (
            DESC_PHOTO[index+1] if index+1<len(DESC_PHOTO) else None
        )
    returned = client.get(f'/api/photos?{query}&page_size=3&anchor_id={DESC_PHOTO[7]}').json()
    assert returned['page'] == 3 and returned['focus_id'] == DESC_PHOTO[7]
    assert [p['id'] for p in returned['items']] == DESC_PHOTO[6:9]
    book = load_workbook(BytesIO(client.get('/api/export.xlsx?'+query).content))
    assert [row[0] for row in list(book['Все фото'].values)[1:]] == DESC_PHOTO


def test_locked_sort_date_basis_agrees_across_list_reports_map_counts_and_export(time_api):
    client, engine = time_api
    expected = [10,70,20,90,50]
    with AccessSession(engine) as db:
        db.get(User,4).permissions = list(DEFAULT_OPERATOR_PERMISSIONS)
        for id in expected:
            db.get(Photo,id).latitude, db.get(Photo,id).longitude = 61.1, 72.6
        db.commit()
    actor(client,4)
    query = 'date_from=2026-10-18&date_to=2026-10-18&date_basis=received&sort_order=asc'
    assert [p['id'] for p in client.get('/api/photos?'+query).json()['items']] == expected
    assert client.get('/api/reports?'+query).json()['total'] == len(expected)
    assert {p['id'] for p in client.get('/api/photos/map?'+query).json()['items']} == set(expected)
    assert client.get('/api/photos/filter-counts?'+query).json()['work_type']['total'] == len(expected)
    book = load_workbook(BytesIO(client.get('/api/export.xlsx?'+query).content))
    assert [row[0] for row in list(book['Все фото'].values)[1:]] == expected


def test_only_admin_can_enable_sorting_and_permissions_remain_opt_in(time_api):
    client, engine = time_api
    assert Permission.PHOTOS_SORT not in DEFAULT_OPERATOR_PERMISSIONS
    permission = next(p for p in client.get('/api/meta').json()['permission_catalog'] if p['code']=='photos_sort')
    assert permission['requires'] == ['photos_view'] and not permission['default_operator']
    assert client.patch('/api/users/4',json={'permissions':['photos_sort']}).status_code == 422
    enabled = client.patch('/api/users/4',json={'permissions':['photos_view','photos_sort']})
    assert enabled.status_code == 200 and enabled.json()['permissions'] == ['photos_view','photos_sort']
    with AccessSession(engine) as db:
        assert db.get(User,4).permissions == ['photos_view','photos_sort']
        assert db.query(LoginSession).filter_by(user_id=4).count() == 0
        audit = db.query(Audit).filter_by(action='USER_UPDATED',object_id=4).order_by(Audit.id.desc()).first()
        assert audit.new_value['permissions'] == ['photos_view','photos_sort']
    disabled = client.patch('/api/users/4',json={'permissions':['photos_view']})
    assert disabled.status_code == 200 and disabled.json()['permissions'] == ['photos_view']
    actor(client,2)
    assert client.patch('/api/users/4',json={'permissions':['photos_view','photos_sort']}).status_code == 403


def test_enabled_operator_and_admin_keep_all_sort_choices(time_api):
    client, engine = time_api
    for user_id in (4,1):
        with AccessSession(engine) as db:
            db.get(User,user_id).permissions = ['photos_view','photos_sort'] if user_id==4 else []
            db.commit()
        actor(client,user_id)
        assert 'photos_sort' in client.get('/api/auth/me').json()['permissions']
        for basis,order,expected in [('photo','asc',ASC_PHOTO),('photo','desc',DESC_PHOTO),
                                     ('received','asc',ASC_RECEIVED),('received','desc',DESC_RECEIVED)]:
            result = client.get(f'/api/photos?date_basis={basis}&sort_order={order}').json()
            assert [p['id'] for p in result['items']] == expected
