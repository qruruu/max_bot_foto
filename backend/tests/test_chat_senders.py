"""Check sender registration, historical photo lookup and chat access boundaries."""
import runpy
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select, update
from test_chat_access import AccessSession, actor
from test_chat_access import access_api as access_api

from app.models import Audit, Chat, ChatSender, Photo, User

LARGE_ID = 9007199254740993


@pytest.fixture
def senders_api(access_api):
    client, engine = access_api
    ChatSender.__table__.create(engine)
    with AccessSession(engine) as db:
        for photo_id, sender_id in [(10,LARGE_ID),(20,LARGE_ID),(30,111),(50,321),(60,777)]:
            db.execute(update(Photo).where(Photo.id == photo_id).values(sender_id=sender_id))
        db.add_all([ChatSender(chat_id=1,sender_id=LARGE_ID,name="Иван · бригада № 2"),
                    ChatSender(chat_id=2,sender_id=LARGE_ID,name="Подпись в другом чате"),
                    ChatSender(chat_id=1,sender_id=999,name="Ещё не присылал фото")])
        db.commit()
    return client, engine


def test_directory_combines_registered_users_and_senders_seen_in_this_chat(senders_api):
    client, _ = senders_api
    result = client.get('/api/chats/1/senders')
    assert result.status_code == 200, result.text
    rows = {row['sender_id']: row for row in result.json()}
    assert rows.keys() == {str(LARGE_ID),'111','321','999'}
    assert rows[str(LARGE_ID)]['name'] == 'Иван · бригада № 2'
    assert rows[str(LARGE_ID)]['photo_count'] == 1
    assert rows['999']['photo_count'] == 0 and rows['999']['last_photo_at'] is None
    assert rows['321']['name'] is None and rows['321']['last_photo_at']
    assert all(row['name'] != 'Подпись в другом чате' for row in rows.values())


def test_photo_detail_uses_the_current_alias_for_its_own_chat_and_exact_id(senders_api):
    client, _ = senders_api
    data = client.get('/api/photos/10').json()
    assert data['sender_id'] == str(LARGE_ID) and data['sender_name'] == 'Иван · бригада № 2'
    result = client.put(f'/api/chats/1/senders/{LARGE_ID}',json={'name':'  Иван Петров  '})
    assert result.status_code == 200 and result.json() == {'sender_id':str(LARGE_ID),'name':'Иван Петров'}
    assert client.get('/api/photos/10').json()['sender_name'] == 'Иван Петров'
    actor(client,1)
    other = client.get('/api/photos/20').json()
    assert other['sender_name'] == 'Подпись в другом чате' and other['sender_id'] == str(LARGE_ID)


def test_unregistered_and_missing_senders_are_not_misattributed(senders_api):
    client, _ = senders_api
    data = client.get('/api/photos/50').json()
    assert data['sender_id'] == '321' and data['sender_name'] is None
    actor(client,1)
    data = client.get('/api/photos/40').json()
    assert data['sender_id'] is None and data['sender_name'] is None
    # A chat with no registered Chat record must not inherit a label from another chat.
    assert client.get('/api/photos/60').json()['sender_name'] is None


def test_manual_registration_and_deleting_label_preserve_photos(senders_api):
    client, engine = senders_api
    assert client.put('/api/chats/1/senders/321',json={'name':'Бригада № 3'}).status_code == 200
    assert client.get('/api/photos/50').json()['sender_name'] == 'Бригада № 3'
    assert client.delete('/api/chats/1/senders/321').status_code == 200
    assert client.delete('/api/chats/1/senders/321').status_code == 200
    data = client.get('/api/photos/50').json()
    assert data['sender_name'] is None and data['sender_id'] == '321' and data['version'] == 1
    with AccessSession(engine) as db:
        assert db.get(Photo,50) is not None
        audit = db.scalar(select(Audit).where(Audit.action=='CHAT_SENDER_REMOVED'))
        assert audit.object_type == 'chat' and audit.object_id == 1
        assert audit.old_value == {'sender_id':'321','name':'Бригада № 3'}


def test_saving_a_participant_twice_updates_instead_of_duplicating(senders_api):
    client, engine = senders_api
    for name in ['Первая подпись','Новая подпись']:
        assert client.put('/api/chats/1/senders/12345',json={'name':name}).status_code == 200
    with AccessSession(engine) as db:
        records = db.scalars(select(ChatSender).where(ChatSender.sender_id == 12345)).all()
        assert len(records) == 1 and records[0].name == 'Новая подпись'


@pytest.mark.parametrize('method', ['GET','PUT','DELETE'])
def test_directory_and_mutations_cannot_cross_chat_boundaries(senders_api,method):
    client, engine = senders_api
    path = '/api/chats/2/senders' + ('' if method=='GET' else f'/{LARGE_ID}')
    assert client.request(method,path,json={'name':'Чужая подпись'} if method=='PUT' else None).status_code == 404
    with AccessSession(engine) as db:
        assert db.get(ChatSender,(2,LARGE_ID)).name == 'Подпись в другом чате'
    assert client.request(method,path.replace('/chats/2/','/chats/999/'),
                          json={'name':'Подпись'} if method=='PUT' else None).status_code == 404


@pytest.mark.parametrize('method', ['GET','PUT','DELETE'])
def test_participant_settings_require_chat_management_but_photo_readers_see_names(senders_api,method):
    client, engine = senders_api
    with AccessSession(engine) as db:
        db.get(User,2).permissions = ['photos_view']
        db.commit()
    assert client.get('/api/photos/10').json()['sender_name'] == 'Иван · бригада № 2'
    path = '/api/chats/1/senders' + ('' if method=='GET' else '/321')
    assert client.request(method,path,json={'name':'Имя'} if method=='PUT' else None).status_code == 403
    client.cookies.clear()
    assert client.request(method,path,json={'name':'Имя'} if method=='PUT' else None).status_code == 401


def test_spam_and_removed_previews_do_not_leak_through_discovered_senders(senders_api):
    client, engine = senders_api
    with AccessSession(engine) as db:
        db.get(User,2).permissions = ['chats_manage']
        db.get(Photo,50).preview_removed_at = db.get(Photo,50).received_at
        db.commit()
    ids = {item['sender_id'] for item in client.get('/api/chats/1/senders').json()}
    assert '111' not in ids and '321' not in ids
    assert str(LARGE_ID) in ids


@pytest.mark.parametrize('id', ['0','-1','1.5','nan',str(2**63)])
def test_invalid_ids_are_rejected_without_writes(senders_api,id):
    client, _ = senders_api
    assert client.put(f'/api/chats/1/senders/{id}',json={'name':'Имя'}).status_code == 422


@pytest.mark.parametrize('body', [{'name':''},{'name':'  '},{'name':'x'*151},{'name':None},
                                  {'name':'Имя','sender_id':4},{}])
def test_invalid_labels_are_rejected(senders_api,body):
    client, _ = senders_api
    assert client.put('/api/chats/1/senders/123',json=body).status_code == 422


def test_largest_supported_id_is_round_tripped_without_precision_loss(senders_api):
    client, _ = senders_api
    id = str(2**63-1)
    assert client.put(f'/api/chats/1/senders/{id}',json={'name':'Большой ID'}).json()['sender_id'] == id
    assert id in {row['sender_id'] for row in client.get('/api/chats/1/senders').json()}


def test_sender_table_migration_keeps_existing_chat_and_photo_rows():
    migration = runpy.run_path(str(Path(__file__).parents[1] / 'alembic/versions/0021_chat_senders.py'))
    engine = create_engine('sqlite://')
    Chat.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(Chat.__table__.insert().values(id=1,max_chat_id=100,name='Чат',active=True))
        with Operations.context(MigrationContext.configure(connection)):
            migration['upgrade']()
        connection.execute(ChatSender.__table__.insert().values(chat_id=1,sender_id=LARGE_ID,name='Иван'))
        assert connection.scalar(select(ChatSender.name)) == 'Иван'
        assert connection.scalar(select(Chat.name)) == 'Чат'
        with Operations.context(MigrationContext.configure(connection)):
            migration['downgrade']()
        assert connection.scalar(select(Chat.name)) == 'Чат'
    engine.dispose()
