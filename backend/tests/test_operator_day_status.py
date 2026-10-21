from sqlalchemy import text
from test_chat_access import AccessSession, actor
from test_chat_access import access_api as access_api
from test_day_reviews import DAY, ROOT, add_photo, close

from app.models import Chat, ExchangeState, Photo, User
from app.permissions import PERMISSIONS

STATUS = ROOT + "/operators"


def rows(client):
    response = client.get(STATUS)
    assert response.status_code == 200, response.text
    return {item['id']: item for item in response.json()['items']}


def test_only_multi_chat_report_readers_can_see_progress(access_api):
    client, engine = access_api
    assert client.get(STATUS).status_code == 403
    actor(client, 3)
    assert client.get(STATUS).status_code == 403
    actor(client, 4)
    result = rows(client)
    assert set(result) == {1, 2, 4}
    assert result[2]['chats'] == [{'id': 1, 'name': 'Разрешённый'}]
    assert result[2]['status'] == 'NOT_CLOSED' and result[2]['total'] == 2
    with AccessSession(engine) as db:
        db.get(User, 4).permissions = ['reports_view']
        db.commit()
    assert rows(client)[4]['status'] == 'NO_PERMISSION'
    assert client.get(ROOT).status_code == 403
    with AccessSession(engine) as db:
        db.get(User, 4).permissions = ['photos_view']
        db.commit()
    assert client.get(STATUS).status_code == 403


def test_personal_closing_and_late_additions_are_not_attributed_to_another_operator(access_api):
    client, engine = access_api
    close(client)  # User 2 closes only chat 100.
    actor(client, 4)
    result = rows(client)
    assert result[2]['status'] == 'CLOSED' and result[2]['last_closed_at']
    assert result[4]['status'] == 'NOT_CLOSED' and result[4]['last_closed_at'] is None
    assert result[2]['confirmed_by'] == ['Оператор 2']
    close(client)  # User 4 closes the remaining chats.
    result = rows(client)
    assert result[4]['status'] == result[2]['status'] == 'CLOSED'
    add_photo(engine)
    result = rows(client)
    assert result[2]['status'] == result[4]['status'] == 'ADDITIONS'
    assert (result[2]['total'], result[2]['confirmed'], result[2]['pending']) == (3, 2, 1)
    close(client)
    assert rows(client)[4]['status'] == 'CLOSED'
    assert rows(client)[2]['status'] == 'CLOSED_BY_OTHER'
    with AccessSession(engine) as db:
        db.get(Photo, 10).is_defect = True
        db.commit()
    assert rows(client)[2]['status'] == 'ADDITIONS'


def test_closing_by_administrator_is_shown_as_another_persons_action(access_api):
    client, _ = access_api
    actor(client, 1)
    close(client)
    result = rows(client)
    assert result[1]['status'] == 'CLOSED'
    assert result[2]['status'] == 'CLOSED_BY_OTHER'
    assert result[2]['last_closed_at'] is None
    assert result[2]['confirmed_by'] == ['Оператор 1']


def test_shared_operators_never_disclose_other_chats_counts_or_unrelated_people(access_api):
    client, engine = access_api
    with AccessSession(engine) as db:
        db.add(Chat(id=3, max_chat_id=300, name='Второй разрешённый', active=True))
        db.get(User, 4).allowed_chat_ids = [1, 3]
        db.add(User(id=5, login='private', name='Скрытый сотрудник', role='OPERATOR', active=True,
                    password_hash='unused', permissions=list(PERMISSIONS), allowed_chat_ids=[2]))
        db.add(User(id=6, login='shared', name='Общий сотрудник', role='OPERATOR', active=True,
                    password_hash='unused', permissions=list(PERMISSIONS), allowed_chat_ids=[1, 2]))
        db.commit()
    actor(client, 4)
    result = rows(client)
    assert 5 not in result
    assert result[6]['chats'] == [{'id': 1, 'name': 'Разрешённый'}]
    assert result[6]['total'] == 2
    assert 'Закрытый' not in client.get(STATUS).text
    assert 'Скрытый сотрудник' not in client.get(STATUS).text
    assert result[1]['total'] == 2  # Neither inaccessible chat 200 nor orphan chat 999.


def test_modes_and_empty_dates_have_independent_statuses(access_api):
    client, engine = access_api
    close(client)
    actor(client, 4)
    add_photo(engine)
    with AccessSession(engine) as db:
        db.get(Photo, 70).cohort = 'test'
        db.commit()
    assert rows(client)[2]['status'] == 'CLOSED'
    with AccessSession(engine) as db:
        db.get(ExchangeState, 1).intake_cohort = 'test'
        db.commit()
    assert rows(client)[2]['status'] == 'NOT_CLOSED'
    assert rows(client)[2]['total'] == 1
    empty = client.get('/api/day-reviews/2026-10-17/operators').json()
    assert all(item['status'] == 'NO_PHOTOS' for item in empty['items'])


def test_work_district_matrix_matches_scoped_photo_lists_and_counts_no_spam(access_api):
    client, engine = access_api
    with AccessSession(engine) as db:
        db.execute(text("INSERT INTO districts(id,name,active) VALUES (1,'Первый',true),(2,'Второй',true)"))
        db.get(Photo, 10).district_id = 1
        db.get(Photo, 20).district_id = 2
        db.get(Photo, 20).work_type = 'LAWN_RAKING'
        db.get(Photo, 50).work_type = None
        db.commit()
    for user_id in (2, 4):
        actor(client, user_id)
        filters = {'date_from': DAY, 'date_to': DAY, 'date_basis': 'photo', 'work_only': 'true'}
        report = client.get('/api/reports', params=filters).json()
        assert sum(item['count'] for item in report['work_district_matrix']) == report['total']
        for cell in report['work_district_matrix']:
            photos = client.get('/api/photos', params={**filters, 'work_type': cell['work_type'], 'district_id': cell['district_id']}).json()
            assert photos['total'] == cell['count']
        if user_id == 2:
            assert all(item['district_id'] != 2 for item in report['work_district_matrix'])
        assert client.get('/api/reports', params={**filters, 'status': 'SPAM'}).json()['work_district_matrix'] == []
        from io import BytesIO

        from openpyxl import load_workbook
        book = load_workbook(BytesIO(client.get('/api/export.xlsx', params=filters).content))
        exported = list(book['Вид работы × микрорайон'].values)
        assert sum(row[-1] for row in exported[1:]) == report['total']
        assert all(sum(row[1:-1]) == row[-1] for row in exported[1:])
