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
