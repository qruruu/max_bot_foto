import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_appeal_workflow import inspector_metadata, metadata, multipart, submit
from test_appeal_workflow import workflow as workflow
from test_inspections import inspection as inspection
from test_organizations import companies as companies

from app.appeals_public import app as public_app
from app.models import CitizenAppeal
from app.organization_registry import control_session

pytestmark = pytest.mark.integration


def test_short_descriptions_and_no_public_checkbox(workflow):
    _, scopes, _, _, addresses, inspectors = workflow
    with TestClient(public_app) as citizen:
        body = metadata(scopes[0], addresses[0])
        body.pop('public_consent')
        assert submit(citizen, {**body, 'description': 'Мусор'}).status_code == 201
        assert submit(citizen, {**body, 'description': '  '}).status_code == 422
    endpoint = f'/api/inspection/organizations/{scopes[0].id}/appeals'
    body = {**inspector_metadata(scopes[0], addresses[0]), 'description': 'Грязь'}
    assert multipart(inspectors[0], endpoint, {**body, 'contact': 'Лишний контакт'}).status_code == 422
    assert multipart(inspectors[0], endpoint, body).status_code == 201


def test_discussion_history_and_operator_status_access(workflow):
    owner, scopes, operators, operator_ids, addresses, inspectors = workflow
    inspection_endpoint = f'/api/inspection/organizations/{scopes[0].id}/appeals'
    created = multipart(inspectors[0], inspection_endpoint, inspector_metadata(scopes[0], addresses[0]))
    id = created.json()['id']
    endpoint = scopes[0].prefix + f'/api/appeals/{id}'
    inspection_endpoint += f'/{id}'
    body = {'client_id': str(uuid4()), 'comment': 'Уточнение от проверяющего'}
    first = inspectors[0].post(inspection_endpoint + '/comments', json=body)
    assert first.status_code == 201, first.text
    assert inspectors[0].post(inspection_endpoint + '/comments', json=body).json() == first.json()
    assert inspectors[1].get(inspection_endpoint + '/events').status_code == 404
    assert inspectors[1].post(inspection_endpoint + '/comments', json=body).status_code == 404
    assert operators[0].get(endpoint + '/events').status_code == 404
    assert owner.post(endpoint + '/assign', json={'operator_id': operator_ids[0], 'instruction': 'secret-task-note', 'expected_version': 1}).status_code == 200
    assert owner.patch(endpoint, json={'status': 'ASSIGNED', 'owner_note': 'secret-admin-note', 'expected_version': 2}).status_code == 200
    assert operators[0].post(endpoint + '/comments', json={'client_id': str(uuid4()), 'comment': 'Ответ оператора'}).status_code == 201
    operator_events = operators[0].get(endpoint + '/events').json()
    assert 'secret-task-note' in json.dumps(operator_events)
    assert 'secret-admin-note' not in json.dumps(operator_events)
    inspector_events = inspectors[0].get(inspection_endpoint + '/events').json()
    assert 'secret-' not in json.dumps(inspector_events)
    assert len([event for event in inspector_events['items'] if event['kind'] == 'COMMENT']) == 2
    assert 'Ответ оператора' in json.dumps(inspector_events, ensure_ascii=False)
    assert operators[0].post(endpoint + '/task-status', json={'status': 'IN_PROGRESS', 'expected_version': 3}).status_code == 200
    assert operators[0].post(endpoint + '/task-status', json={'status': 'ASSIGNED', 'expected_version': 4}).status_code == 200
    assert operators[0].post(endpoint + '/task-status', json={'status': 'IN_PROGRESS', 'expected_version': 4}).status_code == 409
    reported = multipart(operators[0], endpoint + '/result', {'status': 'CANCELLED', 'comment': 'Нужна другая техника', 'expected_version': 5})
    assert reported.status_code == 200, reported.text
    events = inspectors[0].get(inspection_endpoint + '/events').json()['items']
    assert events[-1]['kind'] == 'RESULT' and events[-1]['status'] == 'CANCELLED'
    assert events[-1]['comment'] == 'Нужна другая техника'
    cursor = events[-2]['id']
    assert [event['id'] for event in inspectors[0].get(inspection_endpoint + '/events', params={'after': cursor}).json()['items']] == [events[-1]['id']]
    assert all(event['id'] < cursor for event in inspectors[0].get(inspection_endpoint + '/events', params={'before': cursor}).json()['items'])
    assert owner.get(scopes[0].prefix + '/api/appeals/notifications').json()['new_count'] == 1
    with TestClient(public_app) as citizen:
        assert citizen.get(f'/api/public/appeals/wall/{id}').status_code == 404
        assert citizen.get(f'/api/public/appeals/wall/{id}/events').status_code == 404


def test_archive_preserves_public_response_and_can_be_restored(workflow):
    owner, scopes, operators, _, addresses, inspectors = workflow
    with TestClient(public_app) as citizen:
        assert submit(citizen, metadata(scopes[0], addresses[0])).status_code == 201
        list_endpoint = scopes[0].prefix + '/api/appeals'
        id = owner.get(list_endpoint).json()['items'][0]['id']
        endpoint = list_endpoint + f'/{id}'
        assert owner.post(endpoint + '/archive', json={'archived': True, 'expected_version': 1}).status_code == 409
        closed = multipart(owner, endpoint + '/close', {'comment': 'Проблема устранена', 'expected_version': 1})
        assert closed.status_code == 200, closed.text
        archived = owner.post(endpoint + '/archive', json={'archived': True, 'expected_version': 2})
        assert archived.status_code == 200, archived.text
        assert owner.get(list_endpoint).json()['total'] == 0
        assert owner.get(list_endpoint, params={'archived': True}).json()['total'] == 1
        inspection_endpoint = f'/api/inspection/organizations/{scopes[0].id}/appeals'
        assert inspectors[0].get(inspection_endpoint).json()['total'] == 0
        assert inspectors[0].get(inspection_endpoint, params={'archived': True}).json()['total'] == 1
        assert owner.post(endpoint + '/comments', json={'client_id': str(uuid4()), 'comment': 'Позднее сообщение'}).status_code == 409
        assert operators[0].post(endpoint + '/archive', json={'archived': False, 'expected_version': 3}).status_code == 403
        public = citizen.get(f'/api/public/appeals/wall/{id}').json()
        assert public['response']['comment'] == 'Проблема устранена'
        assert citizen.get(public['response']['photos'][0]['url']).status_code == 200
        assert owner.post(endpoint + '/archive', json={'archived': False, 'expected_version': 3}).status_code == 200
        assert owner.get(list_endpoint).json()['total'] == 1
        assert [event['kind'] for event in owner.get(endpoint + '/events').json()['items']] == ['CREATED', 'CLOSED', 'ARCHIVED', 'RESTORED']


def test_wall_search_text_numbers_and_local_dates_never_searches_private_fields(workflow):
    owner, scopes, _, _, addresses, inspectors = workflow
    with TestClient(public_app) as citizen:
        first = submit(citizen, {**metadata(scopes[0], addresses[0]), 'description': 'Мусор возле фонаря'})
        assert first.status_code == 201, first.text
        second = submit(citizen, {**metadata(scopes[0], addresses[0]), 'description': 'Сломанная урна'})
        assert second.status_code == 201
        assert multipart(inspectors[0], f'/api/inspection/organizations/{scopes[0].id}/appeals',
                         {**inspector_metadata(scopes[0], addresses[0]), 'description': 'Только проверяющему'}).status_code == 201
        first_id = int(first.json()['number'].split('-')[-1])
        second_id = int(second.json()['number'].split('-')[-1])
        with control_session() as db:
            one, two = db.get(CitizenAppeal, first_id), db.get(CitizenAppeal, second_id)
            # UTC evening is already the next day in the configured organization timezone.
            one.created_at = datetime(2026, 10, 20, 22, 30, tzinfo=UTC)
            two.created_at = datetime(2026, 10, 22, 7, 30, tzinfo=UTC)
            one.owner_note, one.contact, one.public_response = 'Служебныйсекрет', 'Личныйконтакт', 'Неопубликованныйответ'
            db.commit()
        def search(q, **params):
            response = citizen.get('/api/public/appeals/wall', params={'city': 'Сургут', 'q': q, **params})
            assert response.status_code == 200, response.text
            return response.json()
        for query in ('МУСОР фонаря', '21 10 2026', '21.10.2026', '2026-10-21'):
            assert [item['id'] for item in search(query)['items']] == [first_id]
        assert search('22.10.2026')['items'][0]['id'] == second_id
        for query in ('20.10.2026', 'Служебныйсекрет', 'Личныйконтакт', 'Неопубликованныйответ', 'Только проверяющему', '%', '_'):
            assert search(query)['total'] == 0
        assert search('фонаря', organization_id=scopes[1].id)['total'] == 0
        assert search('фонаря', city='Тюмень')['total'] == 0
        assert search('   ')['total'] == 2
        assert multipart(owner, scopes[0].prefix + f'/api/appeals/{first_id}/close',
                         {'comment': 'Очистили площадку', 'expected_version': 1}).status_code == 200
        assert search('Очистили')['total'] == 1


def test_spam_can_be_archived_and_restored_without_reappearing_publicly(workflow):
    owner, scopes, _, _, addresses, _ = workflow
    with TestClient(public_app) as citizen:
        created = submit(citizen, metadata(scopes[0], addresses[0]))
        assert created.status_code == 201
        id = int(created.json()['number'].split('-')[-1])
        endpoint = scopes[0].prefix + f'/api/appeals/{id}'
        assert owner.patch(endpoint, json={'status': 'SPAM', 'owner_note': '', 'expected_version': 1}).status_code == 200
        assert owner.post(endpoint + '/archive', json={'archived': True, 'expected_version': 2}).status_code == 200
        archived = owner.get(scopes[0].prefix + '/api/appeals', params={'archived': True}).json()
        assert archived['total'] == 1 and archived['items'][0]['status'] == 'SPAM'
        assert owner.post(endpoint + '/archive', json={'archived': False, 'expected_version': 3}).status_code == 200
        assert owner.get(endpoint).json()['status'] == 'SPAM'
        assert citizen.get(f'/api/public/appeals/wall/{id}').status_code == 404
        assert citizen.get('/api/public/appeals/wall', params={'city': 'Сургут', 'q': 'Урна'}).json()['total'] == 0


def test_message_notifications_are_personal_and_clear_only_after_reply(workflow):
    owner, scopes, operators, operator_ids, addresses, inspectors = workflow
    inbox = scopes[0].prefix + '/api/appeals'
    inspection = f'/api/inspection/organizations/{scopes[0].id}/appeals'
    created = multipart(inspectors[0], inspection, inspector_metadata(scopes[0], addresses[0]))
    id = created.json()['id']
    endpoint, checked = inbox + f'/{id}', inspection + f'/{id}'
    inspector_message = {'client_id': str(uuid4()), 'comment': 'Проверьте урну'}
    assert inspectors[0].post(checked + '/comments', json=inspector_message).status_code == 201
    assert owner.post(endpoint + '/assign', json={'operator_id': operator_ids[0], 'expected_version': 1}).status_code == 200
    def count(client, path):
        detail = client.get(path + f'/{id}').json()
        listing = client.get(path).json()['items'][0]
        assert detail['unanswered_comments'] == listing['unanswered_comments']
        return listing['unanswered_comments']
    assert count(inspectors[0], inspection) == 0
    assert count(owner, inbox) == count(operators[0], inbox) == 1
    # Merely reading the card, history and pictures must not clear the notification.
    assert owner.get(endpoint + '/events').status_code == 200
    assert count(owner, inbox) == 1
    admin_message = {'client_id': str(uuid4()), 'comment': 'Приняли в работу'}
    assert owner.post(endpoint + '/comments', json=admin_message).status_code == 201
    assert count(owner, inbox) == 0
    assert count(inspectors[0], inspection) == 1 and count(operators[0], inbox) == 2
    assert operators[0].post(endpoint + '/comments', json={'client_id': str(uuid4()), 'comment': 'Выезжаю'}).status_code == 201
    assert count(operators[0], inbox) == 0 and count(owner, inbox) == 1
    assert count(inspectors[0], inspection) == 2
    # An idempotent retry of an older reply does not acknowledge newer messages.
    assert owner.post(endpoint + '/comments', json=admin_message).status_code == 201
    assert count(owner, inbox) == 1
    assert inspectors[0].post(checked + '/comments', json={'client_id': str(uuid4()), 'comment': 'Жду результат'}).status_code == 201
    assert count(inspectors[0], inspection) == 0
    assert count(owner, inbox) == 2 and count(operators[0], inbox) == 1
    assert inspectors[1].get(inspection).status_code == 404


def test_inspector_changes_task_status_without_managing_or_publishing_an_appeal(workflow):
    owner, scopes, operators, operator_ids, addresses, inspectors = workflow
    inbox = scopes[0].prefix + '/api/appeals'
    inspection = f'/api/inspection/organizations/{scopes[0].id}/appeals'
    id = multipart(inspectors[0], inspection, inspector_metadata(scopes[0], addresses[0])).json()['id']
    endpoint, checked = inbox + f'/{id}', inspection + f'/{id}'
    assert owner.post(endpoint + '/assign', json={'operator_id': operator_ids[0], 'expected_version': 1}).status_code == 200
    detail = inspectors[0].get(checked).json()
    assert detail['version'] == 2 and detail['can_set_task_status']
    assert not detail['can_manage'] and not detail['can_execute']
    assert inspectors[1].post(checked + '/task-status', json={'status': 'COMPLETED', 'expected_version': 2}).status_code == 404
    assert inspectors[0].post(checked + '/task-status', json={'status': 'RESOLVED', 'expected_version': 2}).status_code == 422
    for status, version in [('COMPLETED', 2), ('CANCELLED', 3)]:
        result = inspectors[0].post(checked + '/task-status', json={'status': status, 'expected_version': version})
        assert result.status_code == 200, result.text
        task = operators[0].get(endpoint).json()
        assert task['status'] == task['task']['status'] == status
    assert inspectors[0].post(checked + '/task-status', json={'status': 'COMPLETED', 'expected_version': 2}).status_code == 409
    events = owner.get(endpoint + '/events').json()['items']
    changes = [item for item in events if item['kind'] == 'STATUS']
    assert [(item['status'], item['actor_role']) for item in changes] == [('COMPLETED', 'INSPECTOR'), ('CANCELLED', 'INSPECTOR')]
    closed = multipart(owner, endpoint + '/close', {'comment': 'Принято решение', 'expected_version': 4}, False)
    assert closed.status_code == 200, closed.text
    assert not inspectors[0].get(checked).json()['can_set_task_status']
    assert inspectors[0].post(checked + '/task-status', json={'status': 'COMPLETED', 'expected_version': 5}).status_code == 409
    # A new complaint need not have an operator assignment to receive the inspector's decision.
    other = multipart(inspectors[0], inspection, inspector_metadata(scopes[0], addresses[0])).json()['id']
    result = inspectors[0].post(inspection + f'/{other}/task-status', json={'status': 'COMPLETED', 'expected_version': 1})
    assert result.status_code == 200, result.text


def test_admin_closes_or_refuses_without_photos_and_publishes_only_the_response(workflow):
    owner, scopes, operators, operator_ids, addresses, inspectors = workflow
    inbox = scopes[0].prefix + '/api/appeals'
    with TestClient(public_app) as citizen:
        for status in ('RESOLVED', 'DECLINED', 'CANCELLED', 'REJECTED'):
            created = submit(citizen, metadata(scopes[0], addresses[0]))
            id = int(created.json()['number'].split('-')[-1])
            endpoint = inbox + f'/{id}'
            version = 1
            if status != 'RESOLVED':
                assert owner.post(endpoint + '/assign', json={'operator_id': operator_ids[0], 'expected_version': 1}).status_code == 200
                version = 2
            assert multipart(owner, endpoint + '/close', {'status': status, 'comment': '  ', 'expected_version': version}, False).status_code == 422
            result = multipart(owner, endpoint + '/close', {'status': status, 'comment': 'Ответ по обращению', 'expected_version': version}, False)
            assert result.status_code == 200, result.text
            public = citizen.get(f'/api/public/appeals/wall/{id}').json()
            assert public['status'] == status and public['response']['photos'] == []
            assert public['response']['comment'] == 'Ответ по обращению'
            assert 'unanswered_comments' not in public
            if status != 'RESOLVED':
                assert operators[0].get(endpoint).json()['task']['status'] == 'CANCELLED'
            checked = f'/api/inspection/organizations/{scopes[0].id}/appeals/{id}'
            assert not inspectors[0].get(checked).json()['can_set_task_status']
            assert owner.post(endpoint + '/archive', json={'archived': True, 'expected_version': version + 1}).status_code == 200
            assert citizen.get(f'/api/public/appeals/wall/{id}').json()['response'] == public['response']
            assert owner.post(endpoint + '/archive', json={'archived': False, 'expected_version': version + 2}).status_code == 200


@pytest.mark.parametrize('status,label', [('CANCELLED', 'Задача отменена'), ('REJECTED', 'Исполнитель отклонил')])
@pytest.mark.parametrize('public', [True, False])
def test_final_cancel_or_reject_stops_task_preserves_visibility_and_can_reopen(workflow, status, label, public):
    owner, scopes, operators, operator_ids, addresses, inspectors = workflow
    inbox = scopes[0].prefix + '/api/appeals'
    inspection = f'/api/inspection/organizations/{scopes[0].id}/appeals'
    with TestClient(public_app) as citizen:
        created = (submit(citizen, metadata(scopes[0], addresses[0])) if public else
                   multipart(inspectors[0], inspection, inspector_metadata(scopes[0], addresses[0])))
        assert created.status_code == 201, created.text
        id = int(created.json()['number'].split('-')[-1])
        endpoint, checked = inbox + f'/{id}', inspection + f'/{id}'
        assert owner.post(endpoint + '/assign', json={'operator_id': operator_ids[0], 'expected_version': 1}).status_code == 200
        decision = {'status': status, 'comment': 'Уникальное объяснение решения', 'expected_version': 2}
        # Final decisions require the close action and the administrator's role.
        assert owner.patch(endpoint, json={'status': status, 'owner_note': '', 'expected_version': 2}).status_code == 422
        assert multipart(operators[0], endpoint + '/close', decision).status_code == 403
        closed = multipart(owner, endpoint + '/close', decision)
        assert closed.status_code == 200, closed.text
        detail = owner.get(endpoint).json()
        assert detail['status'] == status and detail['resolved_at'] and detail['is_final']
        assert detail['task']['status'] == 'CANCELLED' and len(detail['response_photos']) == 1
        assert owner.get(inbox, params={'status': status, 'q': 'Уникальное объяснение'}).json()['total'] == 1
        assert inspectors[0].get(inspection, params={'status': status}).json()['total'] == 1
        assert not inspectors[0].get(checked).json()['can_set_task_status']
        assert inspectors[0].post(checked + '/task-status', json={'status': 'COMPLETED', 'expected_version': 3}).status_code == 409
        assert multipart(operators[0], endpoint + '/result', {'status': 'COMPLETED', 'comment': 'Поздний отчёт', 'expected_version': 3}).status_code == 409
        assert owner.post(endpoint + '/assign', json={'operator_id': operator_ids[0], 'expected_version': 3}).status_code == 409
        assert multipart(owner, endpoint + '/close', {**decision, 'expected_version': 3}, False).status_code == 409
        assert owner.get(inbox + '/notifications').json()['new_count'] == 0
        assert operators[0].get(inbox + '/notifications').json()['new_count'] == 0
        wall_url = f'/api/public/appeals/wall/{id}'
        if public:
            wall = citizen.get(wall_url).json()
            assert wall['status'] == status and wall['response']['comment'] == decision['comment']
            photo_url = wall['response']['photos'][0]['url']
            assert citizen.get(photo_url).status_code == 200
            assert label in citizen.get(f'/a/{id}').text
        else:
            assert citizen.get(wall_url).status_code == 404
            assert citizen.get(f'/a/{id}').status_code == 404
        assert owner.post(endpoint + '/archive', json={'archived': True, 'expected_version': 3}).status_code == 200
        archived = owner.get(inbox, params={'archived': True, 'status': status}).json()
        assert archived['total'] == 1 and archived['items'][0]['status'] == status
        assert owner.post(endpoint + '/archive', json={'archived': False, 'expected_version': 4}).status_code == 200
        assert owner.get(endpoint).json()['status'] == status
        assert owner.patch(endpoint, json={'status': 'IN_REVIEW', 'owner_note': '', 'expected_version': 5}).status_code == 200
        assert owner.post(endpoint + '/assign', json={'operator_id': operator_ids[0], 'expected_version': 6}).status_code == 200
        if public:
            assert citizen.get(wall_url).json()['response'] is None
            assert citizen.get(photo_url).status_code == 404


def test_executor_result_can_be_finalized_with_same_status_and_reopened_without_old_answer(workflow):
    owner, scopes, operators, operator_ids, addresses, _ = workflow
    inbox = scopes[0].prefix + '/api/appeals'
    with TestClient(public_app) as citizen:
        for status in ('CANCELLED', 'REJECTED'):
            created = submit(citizen, metadata(scopes[0], addresses[0]))
            id = int(created.json()['number'].split('-')[-1])
            endpoint = inbox + f'/{id}'
            assign = {'operator_id': operator_ids[0], 'expected_version': 1}
            assert owner.post(endpoint + '/assign', json=assign).status_code == 200
            report = {'status': status, 'comment': 'Служебный отчёт исполнителя', 'expected_version': 2}
            assert multipart(operators[0], endpoint + '/result', report).status_code == 200
            assert not owner.get(endpoint).json()['is_final']
            wall_url = f'/api/public/appeals/wall/{id}'
            wall = citizen.get(wall_url).json()
            assert wall['status'] == status and wall['response'] is None and not wall['is_final']
            assert owner.post(endpoint + '/archive', json={'archived': True, 'expected_version': 3}).status_code == 409
            closed = multipart(owner, endpoint + '/close', {'status': status, 'comment': 'Публичное объяснение организации', 'expected_version': 3}, False)
            assert closed.status_code == 200, closed.text
            wall = citizen.get(wall_url).json()
            assert wall['status'] == status and wall['is_final']
            assert wall['response']['comment'] == 'Публичное объяснение организации'
            assert 'Служебный отчёт исполнителя' not in citizen.get(wall_url).text
            assert owner.patch(endpoint, json={'status': 'IN_REVIEW', 'owner_note': '', 'expected_version': 4}).status_code == 200
            assert owner.get(endpoint).json()['resolved_at'] is None
            assert owner.post(endpoint + '/assign', json={**assign, 'expected_version': 5}).status_code == 200
            assert multipart(operators[0], endpoint + '/result', {**report, 'expected_version': 6}).status_code == 200
            wall = citizen.get(wall_url).json()
            assert wall['status'] == status and not wall['is_final'] and wall['response'] is None


def test_operator_updates_only_their_current_assignment_and_loses_access_after_reassignment(workflow):
    from sqlalchemy.orm import Session

    from app.db import engine
    from app.models import User
    from app.organization_context import organization_scope

    owner, scopes, operators, operator_ids, addresses, inspectors = workflow
    scope = scopes[0]
    with organization_scope(scope), Session(engine()) as tenant:
        other = User(login='another-operator', name='Другой оператор', role='OPERATOR', active=True,
                     password_hash=tenant.get(User, operator_ids[0]).password_hash)
        tenant.add(other)
        tenant.flush()
        other_id = other.id
        tenant.commit()
    inbox = scope.prefix + '/api/appeals'
    inspection = f'/api/inspection/organizations/{scope.id}/appeals'
    ids = [multipart(inspectors[0], inspection, inspector_metadata(scope, addresses[0])).json()['id'] for _ in range(2)]
    for id, operator_id in zip(ids, [operator_ids[0], other_id], strict=True):
        assert owner.post(inbox + f'/{id}/assign', json={'operator_id': operator_id, 'expected_version': 1}).status_code == 200
    mine, foreign = [inbox + f'/{id}' for id in ids]
    assert operators[0].post(mine + '/task-status', json={'status': 'IN_PROGRESS', 'expected_version': 2}).status_code == 200
    assert [item['id'] for item in operators[0].get(inbox).json()['items']] == [ids[0]]
    assert operators[0].post(foreign + '/task-status', json={'status': 'ASSIGNED', 'expected_version': 2}).status_code == 404
    assert multipart(operators[0], foreign + '/result', {'status': 'COMPLETED', 'comment': 'Чужая задача', 'expected_version': 2}).status_code == 404
    assert operators[0].post(inspection + f'/{ids[0]}/task-status', json={'status': 'COMPLETED', 'expected_version': 3}).status_code in (401, 403)
    assert owner.post(mine + '/assign', json={'operator_id': other_id, 'expected_version': 3}).status_code == 200
    assert operators[0].get(mine).status_code == 404
    assert operators[0].get(inbox).json()['total'] == 0
    assert operators[0].post(mine + '/task-status', json={'status': 'IN_PROGRESS', 'expected_version': 4}).status_code == 404
    assert multipart(operators[0], mine + '/result', {'status': 'CANCELLED', 'comment': 'Уже переназначено', 'expected_version': 4}).status_code == 404
