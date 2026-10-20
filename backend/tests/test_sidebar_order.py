import pytest
from sqlalchemy import select
from test_chat_access import AccessSession, actor
from test_chat_access import access_api as access_api

from app.models import LoginSession, User
from app.schemas import SIDEBAR_ROUTES


def test_menu_order_persists_for_the_current_account_and_survives_a_new_session(access_api):
    client, engine = access_api
    assert client.get('/api/auth/me').json()['sidebar_order'] == []
    order = ['/photos', '/review', '/', '/messages']
    result = client.put('/api/auth/sidebar-order', json={'sidebar_order':order})
    assert result.status_code == 200 and result.json() == {'sidebar_order':order}
    actor(client, 1)
    assert client.get('/api/auth/me').json()['sidebar_order'] == []
    other = ['/jobs', '/', '/photos']
    assert client.put('/api/auth/sidebar-order', json={'sidebar_order':other}).status_code == 200
    actor(client, 2)
    assert client.get('/api/auth/me').json()['sidebar_order'] == order
    with AccessSession(engine) as db:
        assert db.get(User, 1).sidebar_order == other
        assert db.get(User, 2).sidebar_order == order
        assert db.get(User, 3).sidebar_order == []
        assert len(list(db.scalars(select(LoginSession)))) == 4


def test_menu_order_is_available_without_extra_permissions_and_does_not_grant_access(access_api):
    client, engine = access_api
    with AccessSession(engine) as db:
        db.get(User, 2).permissions = []
        db.commit()
    order = ['/users', '/exchange', '/photos']
    assert client.put('/api/auth/sidebar-order', json={'sidebar_order':order}).status_code == 200
    result = client.get('/api/auth/me').json()
    assert result['sidebar_order'] == order and result['permissions'] == []
    assert result['allowed_chat_ids'] == [1]
    assert client.get('/api/users').status_code == 403
    assert client.get('/api/photos').status_code == 403
    assert client.get('/api/exchange').status_code == 403


def test_reset_order_and_new_user_defaults_are_independent(access_api):
    client, _ = access_api
    assert client.put('/api/auth/sidebar-order', json={'sidebar_order':['/photos']}).status_code == 200
    assert client.put('/api/auth/sidebar-order', json={'sidebar_order':[]}).json() == {'sidebar_order':[]}
    assert client.get('/api/auth/me').json()['sidebar_order'] == []


@pytest.mark.parametrize('body', [
    {'sidebar_order':['/photos','/photos']}, {'sidebar_order':['/unknown']},
    {'sidebar_order':['/photos?admin=1']}, {'sidebar_order':None},
    {'sidebar_order':[1]}, {'sidebar_order':['/photos'] * (len(SIDEBAR_ROUTES)+1)},
    {'sidebar_order':['/photos'], 'user_id':1}, {'sidebar_order':['/photos'], 'permissions':['users_manage']},
])
def test_invalid_sidebar_orders_and_cross_account_payloads_are_rejected(access_api, body):
    client, _ = access_api
    assert client.put('/api/auth/sidebar-order', json=body).status_code == 422
    assert client.get('/api/auth/me').json()['sidebar_order'] == []


def test_menu_save_requires_session_csrf_and_valid_origin(access_api):
    client, _ = access_api
    body = {'sidebar_order':['/photos']}
    assert client.put('/api/auth/sidebar-order', json=body, headers={'X-CSRF-Token':'wrong'}).status_code == 403
    assert client.put('/api/auth/sidebar-order', json=body, headers={'Origin':'https://other.example'}).status_code == 403
    assert client.get('/api/auth/me').json()['sidebar_order'] == []
    client.cookies.clear()
    assert client.put('/api/auth/sidebar-order', json=body).status_code == 401


def test_administrative_user_updates_cannot_overwrite_a_personal_order(access_api):
    client, _ = access_api
    actor(client, 1)
    result = client.patch('/api/users/2', json={'sidebar_order':['/photos']})
    assert result.status_code == 422
    actor(client, 2)
    assert client.get('/api/auth/me').json()['sidebar_order'] == []
