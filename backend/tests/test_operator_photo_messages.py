"""Photo forwarding must retain private chat semantics and existing photo permissions."""

import runpy
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import IntegrityError
from test_chat_access import AccessSession, actor
from test_chat_access import access_api as access_api

from app.models import OperatorMessage, Photo, User


@pytest.fixture
def photo_messages(access_api):
    client, engine = access_api
    OperatorMessage.__table__.create(engine)
    actor(client, 1)
    return client, engine


def forward(client, *, peer=2, photo_id=10, body='Какой вид работ тут выбрать?', key=None):
    return client.post(f'/api/operator-chats/{peer}/messages', json={
        'body': body, 'photo_id': photo_id, 'client_id': key or str(uuid4()),
    })


def test_forward_open_photo_reply_and_read_receipts(photo_messages):
    client, engine = photo_messages
    result = forward(client)
    assert result.status_code == 201, result.text
    message = result.json()
    assert message['photo'] == {'id': 10, 'available': True, 'preview_url': '/api/photos/10/preview'}
    assert message['body'] == 'Какой вид работ тут выбрать?'
    assert client.get('/api/operator-chats').json()['items'][0]['last_message']['photo'] == message['photo']
    actor(client, 2)
    assert client.get('/api/operator-chats/unread').json()['unread'] == 1
    received = client.get('/api/operator-chats/1/messages').json()['items']
    assert len(received) == 1 and received[0]['photo'] == message['photo']
    photo = client.get('/api/photos/10')
    assert photo.status_code == 200 and photo.json()['id'] == 10
    assert client.post('/api/operator-chats/1/read', json={'through_id': message['id']}).status_code == 200
    reply = client.post('/api/operator-chats/1/messages', json={'body': 'Здесь УРНЫ', 'client_id': str(uuid4())})
    assert reply.status_code == 201 and reply.json()['photo'] is None
    actor(client, 1)
    page = client.get('/api/operator-chats/2/messages').json()
    assert [item['body'] for item in page['items']] == [message['body'], 'Здесь УРНЫ']
    assert page['peer_read_through_id'] == message['id']
    with AccessSession(engine) as db:
        photo = db.get(Photo, 10)
        assert photo.version == 1 and photo.work_type == 'BIN_EMPTYING'
        assert photo.sha256 == f'{10:064x}' and photo.storage_status == 'SYNCED'


def test_photo_can_be_forwarded_without_a_comment_and_retried_without_duplicates(photo_messages):
    client, engine = photo_messages
    key = str(uuid4())
    first = forward(client, body='', key=key)
    repeated = forward(client, body='', key=key)
    assert first.status_code == repeated.status_code == 201
    assert first.json()['id'] == repeated.json()['id'] and first.json()['body'] == ''
    assert forward(client, photo_id=50, body='', key=key).status_code == 409
    assert forward(client, body='Другой вопрос', key=key).status_code == 409
    assert forward(client, peer=4, body='', key=key).status_code == 409
    with AccessSession(engine) as db:
        assert db.scalar(select(func.count()).select_from(OperatorMessage)) == 1


def test_recipient_picker_only_shows_active_operators_with_access(photo_messages):
    client, engine = photo_messages
    assert {item['id'] for item in client.get('/api/operator-chats?photo_id=10').json()['items']} == {2, 4}
    assert {item['id'] for item in client.get('/api/operator-chats?photo_id=20').json()['items']} == {4}
    with AccessSession(engine) as db:
        db.get(User, 2).permissions = ['photos_view']
        db.get(User, 4).active = False
        db.commit()
    # Editing is not required: a colleague can simply inspect and answer.
    assert [item['id'] for item in client.get('/api/operator-chats?photo_id=10').json()['items']] == [2]
    assert client.get('/api/operator-chats?photo_id=30').json()['items'] == []


def test_sending_rechecks_recipient_access_after_selection(photo_messages):
    client, engine = photo_messages
    assert any(item['id'] == 2 for item in client.get('/api/operator-chats?photo_id=10').json()['items'])
    with AccessSession(engine) as db:
        db.get(User, 2).allowed_chat_ids = []
        db.commit()
    assert forward(client).status_code == 422
    assert forward(client, photo_id=20).status_code == 422
    with AccessSession(engine) as db:
        assert db.scalar(select(func.count()).select_from(OperatorMessage)) == 0


@pytest.mark.parametrize('photo_id', [20, 40, 60, 999])
def test_sender_cannot_forward_a_photo_outside_own_access(photo_messages, photo_id):
    client, engine = photo_messages
    actor(client, 2)
    assert forward(client, peer=1, photo_id=photo_id).status_code == 404
    assert client.get(f'/api/operator-chats?photo_id={photo_id}').status_code == 404
    with AccessSession(engine) as db:
        assert db.scalar(select(func.count()).select_from(OperatorMessage)) == 0


def test_spam_requires_permission_for_both_participants(photo_messages):
    client, engine = photo_messages
    with AccessSession(engine) as db:
        db.get(User, 2).permissions = ['photos_view']
        db.commit()
    assert forward(client, photo_id=30).status_code == 422
    actor(client, 2)
    assert forward(client, peer=1, photo_id=30).status_code == 404
    assert forward(client, peer=1, photo_id=10).status_code == 201


def test_sender_needs_photo_view_but_does_not_need_edit_permissions(photo_messages):
    client, engine = photo_messages
    actor(client, 2)
    with AccessSession(engine) as db:
        db.get(User, 2).permissions = []
        db.commit()
    assert forward(client, peer=1).status_code == 404
    with AccessSession(engine) as db:
        db.get(User, 2).permissions = ['photos_view']
        db.commit()
    assert forward(client, peer=1).status_code == 201


def test_history_redacts_photo_preview_if_access_is_revoked(photo_messages):
    client, engine = photo_messages
    message = forward(client).json()
    with AccessSession(engine) as db:
        db.get(User, 2).allowed_chat_ids = []
        db.commit()
    actor(client, 2)
    expected = {'id': 10, 'available': False, 'preview_url': None}
    assert client.get('/api/operator-chats/1/messages').json()['items'][0]['photo'] == expected
    assert client.get('/api/operator-chats').json()['items'][0]['last_message']['photo'] == expected
    assert client.get('/api/photos/10').status_code == 404
    assert client.get('/api/photos/10/preview').status_code == 404
    # Revoking photo access does not remove the private question or its reply.
    assert client.post('/api/operator-chats/1/messages', json={'body': 'Не могу открыть фото', 'client_id': str(uuid4())}).status_code == 201
    with AccessSession(engine) as db:
        assert db.get(OperatorMessage, message['id']).body == 'Какой вид работ тут выбрать?'


def test_removing_a_preview_keeps_the_message_but_hides_the_attachment(photo_messages):
    client, engine = photo_messages
    forward(client)
    with AccessSession(engine) as db:
        db.get(Photo, 10).preview_removed_at = db.get(Photo, 10).received_at
        db.commit()
    actor(client, 2)
    assert client.get('/api/operator-chats/1/messages').json()['items'][0]['photo']['available'] is False
    actor(client, 1)
    assert forward(client).status_code == 404


def test_photo_attachment_is_private_to_the_two_correspondents(photo_messages):
    client, _ = photo_messages
    message = forward(client).json()
    actor(client, 4)  # This operator can view the photo, but cannot read another pair's messages.
    assert client.get('/api/operator-chats/1/messages').json()['items'] == []
    assert client.get('/api/operator-chats/2/messages').json()['items'] == []
    assert all(item['last_message'] is None for item in client.get('/api/operator-chats').json()['items'])
    assert client.post('/api/operator-chats/1/read', json={'through_id': message['id']}).status_code == 404


@pytest.mark.parametrize('photo_id', [0, -1, 'invalid'])
def test_invalid_photo_references_are_rejected(photo_messages, photo_id):
    client, _ = photo_messages
    assert forward(client, photo_id=photo_id).status_code == 422


def test_message_migration_preserves_old_history_and_enforces_valid_attachments():
    root = Path(__file__).parents[1] / 'alembic/versions'
    original = runpy.run_path(str(root / '0018_operator_messages.py'))
    migration = runpy.run_path(str(root / '0024_operator_photo_messages.py'))
    engine = create_engine('sqlite://')

    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')

    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE photos (id INTEGER PRIMARY KEY)'))
        connection.execute(text('INSERT INTO users VALUES (1), (2)'))
        connection.execute(text('INSERT INTO photos VALUES (10)'))
        with Operations.context(MigrationContext.configure(connection)):
            original['upgrade']()
        connection.execute(text("INSERT INTO operator_messages (id,sender_id,recipient_id,client_id,body) VALUES (1,1,2,'old','Прежнее сообщение')"))
        before = connection.execute(text('SELECT id,sender_id,recipient_id,client_id,body,created_at,read_at FROM operator_messages')).all()
        with Operations.context(MigrationContext.configure(connection)):
            migration['upgrade']()
        after = connection.execute(text('SELECT id,sender_id,recipient_id,client_id,body,created_at,read_at FROM operator_messages')).all()
        assert before == after
        assert connection.scalar(text('SELECT photo_id FROM operator_messages WHERE id=1')) is None
        connection.execute(text("INSERT INTO operator_messages (id,sender_id,recipient_id,client_id,body,photo_id) VALUES (2,1,2,'photo','',10)"))
        for invalid in ["(3,1,2,'empty','',NULL)", "(3,1,2,'missing','Фото',999)"]:
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(text('INSERT INTO operator_messages (id,sender_id,recipient_id,client_id,body,photo_id) VALUES ' + invalid))
        assert connection.scalar(text('SELECT COUNT(*) FROM operator_messages')) == 2
    with pytest.raises(RuntimeError, match='preserved'):
        migration['downgrade']()
    engine.dispose()
