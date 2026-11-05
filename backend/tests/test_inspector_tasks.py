import base64
import json
from datetime import timedelta
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_appeal_images import frame
from test_appeal_workflow import inspector_metadata, metadata, multipart, submit
from test_appeal_workflow import workflow as workflow
from test_inspections import inspection as inspection
from test_organizations import companies as companies

from app.appeal_files import prepare_document
from app.appeal_reporting import today
from app.appeals_public import app as public_app
from app.auth import hasher
from app.db import engine
from app.models import User
from app.organization_context import organization_scope


def office_file(member):
    result = BytesIO()
    with ZipFile(result, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr(member, '<document/>')
    return result.getvalue()


@pytest.mark.parametrize('name,content', [('a.pdf', b'%PDF-1.7\nexample'),
    ('a.docx', office_file('word/document.xml')), ('a.xlsx', office_file('xl/workbook.xml')),
    ('a.doc', bytes.fromhex('d0cf11e0a1b11ae1') + b'example'), ('a.xls', bytes.fromhex('d0cf11e0a1b11ae1') + b'example')])
def test_document_types_and_download_filename(name, content):
    assert prepare_document(content, '../' + name)['name'] == name
    with pytest.raises(HTTPException):
        prepare_document(b'<script>bad</script>', name)
    with pytest.raises(HTTPException):
        prepare_document(content, 'a.html')


@pytest.mark.integration
def test_optional_fields_documents_chat_audiences_and_deadline_enforcement(workflow):
    owner, scopes, operators, ids, addresses, inspectors = workflow
    checked = f'/api/inspection/organizations/{scopes[0].id}/appeals'
    due = today() + timedelta(days=5)
    body = {**inspector_metadata(scopes[0], addresses[0]), 'address_id': None, 'address': '',
            'latitude': None, 'longitude': None, 'category': '', 'inspector_due_date': str(due)}
    response = inspectors[0].post(checked, data={'metadata': json.dumps(body)}, files=[
        ('documents', ('instructions.pdf', b'%PDF-1.7\ninstructions', 'application/pdf')),
        ('photos', ('photo.jpg', frame(), 'image/jpeg'))])
    assert response.status_code == 201, response.text
    id = response.json()['id']
    checked += f'/{id}'
    endpoint = scopes[0].prefix + f'/api/appeals/{id}'
    detail = inspectors[0].get(checked).json()
    assert detail['latitude'] is None and detail['category'] == ''
    assert detail['can_set_inspector_deadline'] and len(detail['photos']) == 1
    assert inspectors[0].get(detail['files'][0]['url']).content == b'%PDF-1.7\ninstructions'
    assert inspectors[1].get(detail['files'][0]['url']).status_code == 404
    assert owner.post(endpoint + '/assign', json={'operator_id': ids[0], 'expected_version': 1}).status_code == 200
    assert owner.get(endpoint).json()['task']['due_date'] == str(due)
    assert owner.post(endpoint + '/deadline', json={'due_date': str(due + timedelta(days=1)), 'expected_version': 2}).status_code == 422
    assert owner.post(endpoint + '/deadline', json={'due_date': None, 'expected_version': 2}).status_code == 422
    assert inspectors[0].post(checked + '/deadline', json={'due_date': str(due - timedelta(days=1)), 'expected_version': 2}).status_code == 422
    assert owner.post(endpoint + '/deadline', json={'due_date': str(due - timedelta(days=2)), 'expected_version': 2}).status_code == 200
    assert inspectors[0].post(checked + '/deadline', json={'due_date': str(due - timedelta(days=1)), 'expected_version': 3}).status_code == 200
    assert operators[0].post(endpoint + '/deadline', json={'due_date': str(due), 'expected_version': 4}).status_code == 403
    screenshot = base64.b64encode(frame()).decode()
    messages = [
        (inspectors[0], checked, 'inspector', 'checking-private'),
        (operators[0], endpoint, 'executor', 'executor-private'),
        (owner, endpoint, 'inspector', 'admin-checking'),
        (owner, endpoint, 'executor', 'admin-executor')]
    for client, path, channel, text in messages:
        payload = {'client_id': str(uuid4()), 'channel': channel, 'comment': text, 'screenshots': [screenshot]}
        response = client.post(path + '/comments', json=payload)
        assert response.status_code == 201, response.text
        assert client.post(path + '/comments', json=payload).json() == response.json()
    inspector_events = inspectors[0].get(checked + '/events').json()
    executor_events = operators[0].get(endpoint + '/events').json()
    assert 'executor-private' not in json.dumps(inspector_events)
    assert 'checking-private' not in json.dumps(executor_events)
    inspector_file = next(item for item in inspector_events['items'] if item['comment'] == 'checking-private')['files'][0]
    executor_file = next(item for item in executor_events['items'] if item['comment'] == 'executor-private')['files'][0]
    assert owner.get(endpoint + '/files/' + executor_file['id']).status_code == 200
    assert inspectors[0].get(checked + '/files/' + executor_file['id']).status_code == 404
    assert operators[0].get(endpoint + '/files/' + inspector_file['id']).status_code == 404
    assert operators[0].get(endpoint + '/events?channel=inspector').status_code == 403
    assert inspectors[0].post(checked + '/comments', json={'client_id': str(uuid4()), 'channel': 'executor', 'comment': 'bad'}).status_code == 403
    assert owner.post(endpoint + '/comments', json={'client_id': str(uuid4()), 'channel': 'executor', 'screenshots': ['invalid!']}).status_code == 422
    with TestClient(public_app) as citizen:
        assert citizen.get(f'/api/public/appeals/wall/{id}').status_code == 404
        created = submit(citizen, metadata(scopes[0], addresses[0]))
        citizen_id = int(created.json()['number'].split('-')[-1])
    citizen_checked = f'/api/inspection/organizations/{scopes[0].id}/appeals/{citizen_id}'
    assert not inspectors[0].get(citizen_checked).json()['can_set_task_status']
    assert inspectors[0].post(citizen_checked + '/task-status', json={'status': 'COMPLETED', 'expected_version': 1}).status_code == 403
    assert inspectors[0].post(citizen_checked + '/comments', json={'client_id': str(uuid4()), 'comment': 'bad'}).status_code == 403
    assert inspectors[0].post(citizen_checked + '/deadline', json={'due_date': str(due), 'expected_version': 1}).status_code == 403
    assert multipart(owner, scopes[0].prefix + f'/api/appeals/{citizen_id}/close', {'comment': 'Итоговый ответ', 'expected_version': 1}, False).status_code == 200
    assert inspectors[0].get(citizen_checked).json()['public_response'] == 'Итоговый ответ'


@pytest.mark.integration
def test_subtasks_isolate_operators_inherit_deadline_and_block_parent_closure(workflow):
    owner, scopes, operators, ids, addresses, inspectors = workflow
    scope = scopes[0]
    checked = f'/api/inspection/organizations/{scope.id}/appeals'
    due = today() + timedelta(days=4)
    created = multipart(inspectors[0], checked, {**inspector_metadata(scope, addresses[0]), 'inspector_due_date': str(due)})
    assert created.status_code == 201, created.text
    parent_id = created.json()['id']
    endpoint = scope.prefix + f'/api/appeals/{parent_id}'
    with organization_scope(scope), Session(engine()) as tenant:
        other = User(login='subtask-operator', name='Второй оператор', role='OPERATOR', active=True,
                     password_hash=hasher.hash('test-password-123'))
        tenant.add(other)
        tenant.flush()
        other_id = other.id
        tenant.commit()
    assert owner.post(endpoint + '/assign', json={'operator_id': ids[0], 'expected_version': 1}).status_code == 200
    body = {'subject': 'Первая часть', 'description': 'Выполнить первую часть', 'operator_id': ids[0],
            'due_date': str(due + timedelta(days=1)), 'client_id': str(uuid4()), 'expected_version': 2}
    assert owner.post(endpoint + '/subtasks', json=body).status_code == 422
    body['due_date'] = str(due - timedelta(days=1))
    first = owner.post(endpoint + '/subtasks', json=body)
    assert first.status_code == 201, first.text
    assert owner.post(endpoint + '/subtasks', json=body).json() == first.json()
    second = owner.post(endpoint + '/subtasks', json={**body, 'client_id': str(uuid4()), 'subject': 'Вторая часть', 'operator_id': other_id, 'expected_version': 3})
    assert second.status_code == 201, second.text
    one, two = first.json()['id'], second.json()['id']
    first_endpoint, second_endpoint = [scope.prefix + f'/api/appeals/{id}' for id in (one, two)]
    assert operators[0].get(endpoint).status_code == 404
    assert operators[0].get(second_endpoint).status_code == 404
    first_detail = operators[0].get(first_endpoint).json()
    assert first_detail['parent'] is None and first_detail['children'] == []
    assert first_detail['parent_id'] == parent_id and len(first_detail['photos']) == 1
    assert first_detail['inspector_due_date'] == str(due)
    parent = owner.get(endpoint).json()
    assert parent['task'] is None and len(parent['children']) == 2
    assert owner.patch(endpoint, json={'status': 'SPAM', 'owner_note': '', 'expected_version': parent['version']}).status_code == 409
    assert owner.post(endpoint + '/assign', json={'operator_id': ids[0], 'expected_version': parent['version']}).status_code == 409
    assert multipart(owner, endpoint + '/close', {'comment': ' ', 'expected_version': parent['version']}, False).status_code == 422
    assert inspectors[0].post(checked + f'/{parent_id}/deadline', json={'due_date': str(due - timedelta(days=2)), 'expected_version': parent['version']}).status_code == 422
    assert owner.post(first_endpoint + '/deadline', json={'due_date': str(due + timedelta(days=1)), 'expected_version': 1}).status_code == 422
    assert owner.post(first_endpoint + '/subtasks', json={**body, 'client_id': str(uuid4()), 'expected_version': 1}).status_code == 409
    assert inspectors[1].get(checked + f'/{one}').status_code == 404
    for child_endpoint in (first_endpoint, second_endpoint):
        # Administrator can explicitly cancel a child with an explanation.
        assert multipart(owner, child_endpoint + '/close', {'status': 'CANCELLED', 'comment': 'Закрыто с объяснением', 'expected_version': 1}, False).status_code == 200
    assert multipart(owner, endpoint + '/close', {'comment': 'Итог по обеим частям', 'expected_version': parent['version']}, False).status_code == 200
    assert inspectors[0].get(checked + f'/{parent_id}').json()['public_response'] == 'Итог по обеим частям'
    assert owner.patch(first_endpoint, json={'status': 'IN_REVIEW', 'owner_note': '', 'expected_version': 2}).status_code == 409

    assert owner.patch(endpoint, json={'status': 'IN_REVIEW', 'owner_note': '', 'expected_version': parent['version'] + 1}).status_code == 200
    assert owner.patch(first_endpoint, json={'status': 'IN_REVIEW', 'owner_note': '', 'expected_version': 2}).status_code == 200
    assert owner.get(endpoint).json()['status'] == 'IN_PROGRESS'
    assert not owner.get(endpoint).json()['children'][0]['is_final']
    assert owner.get(endpoint).json()['children'][0]['result'] == ''


@pytest.mark.integration
def test_admin_can_close_without_executor_result_and_close_open_children(workflow):
    owner, scopes, operators, ids, addresses, inspectors = workflow
    inbox = scopes[0].prefix + '/api/appeals'
    checked = f'/api/inspection/organizations/{scopes[0].id}/appeals'
    id = multipart(inspectors[0], checked, inspector_metadata(scopes[0], addresses[0])).json()['id']
    endpoint = inbox + f'/{id}'
    assert owner.post(endpoint + '/assign', json={'operator_id': ids[0], 'expected_version': 1}).status_code == 200
    close = {'comment': 'Принято решение закрыть самостоятельно', 'expected_version': 2}
    assert multipart(operators[0], endpoint + '/close', close, False).status_code == 403
    assert multipart(owner, endpoint + '/close', close, False).status_code == 200
    detail = owner.get(endpoint).json()
    assert detail['status'] == 'RESOLVED' and detail['task']['status'] == 'CANCELLED'
    assert detail['task']['result_comment'] == '' and detail['task']['finished_at']
    assert multipart(operators[0], endpoint + '/result', {'status': 'COMPLETED', 'comment': 'Поздний отчёт', 'expected_version': 3}).status_code == 409
    parent_id = multipart(inspectors[0], checked, inspector_metadata(scopes[0], addresses[0])).json()['id']
    parent_endpoint = inbox + f'/{parent_id}'
    child = owner.post(parent_endpoint + '/subtasks', json={'subject': 'Часть задачи', 'description': 'Проверить',
        'operator_id': ids[0], 'client_id': str(uuid4()), 'expected_version': 1})
    assert child.status_code == 201, child.text
    assert multipart(owner, parent_endpoint + '/close', {**close, 'comment': 'Закрываем все части'}, False).status_code == 200
    child_detail = owner.get(inbox + f'/{child.json()["id"]}').json()
    assert child_detail['is_final'] and child_detail['status'] == child_detail['task']['status'] == 'CANCELLED'
    assert 'Закрываем все части' in child_detail['public_response']


@pytest.mark.integration
def test_channel_badges_count_messages_and_clear_only_after_reply(workflow):
    owner, scopes, operators, ids, addresses, inspectors = workflow
    checked = f'/api/inspection/organizations/{scopes[0].id}/appeals'
    id = multipart(inspectors[0], checked, inspector_metadata(scopes[0], addresses[0])).json()['id']
    endpoint = scopes[0].prefix + f'/api/appeals/{id}'
    checked += f'/{id}'
    assert owner.post(endpoint + '/assign', json={'operator_id': ids[0], 'expected_version': 1}).status_code == 200
    for _ in range(2):
        assert inspectors[0].post(checked + '/comments', json={'client_id': str(uuid4()), 'comment': 'Уточнение'}).status_code == 201
    assert operators[0].post(endpoint + '/comments', json={'client_id': str(uuid4()), 'comment': 'Сообщение исполнителя'}).status_code == 201
    def count(channel):
        return owner.get(endpoint + '/events', params={'channel': channel}).json()['unanswered_comments']
    assert count('inspector') == 2 and count('executor') == 1
    assert count('inspector') == 2  # Viewing the tab does not acknowledge messages.
    assert owner.post(endpoint + '/comments', json={'client_id': str(uuid4()), 'channel': 'inspector', 'comment': 'Ответ проверяющему'}).status_code == 201
    assert count('inspector') == 0 and count('executor') == 1
    assert operators[0].get(endpoint + '/events?channel=inspector').status_code == 403
    assert 'Ответ проверяющему' not in operators[0].get(endpoint + '/events').text
    assert owner.post(endpoint + '/comments', json={'client_id': str(uuid4()), 'channel': 'executor', 'comment': 'Ответ исполнителю'}).status_code == 201
    assert count('executor') == 0
    assert inspectors[0].get(checked + '/events').json()['unanswered_comments'] == 1
    assert inspectors[0].get(checked.rsplit('/',1)[0]).json()['public_url']
    assert operators[0].get(scopes[0].prefix + '/api/appeals').json()['public_url']


@pytest.mark.integration
def test_source_filter_separates_signal_and_inspector_in_lists_archives_and_statistics(workflow):
    owner, scopes, _, _, addresses, inspectors = workflow
    inbox = scopes[0].prefix + '/api/appeals'
    checked = f'/api/inspection/organizations/{scopes[0].id}/appeals'
    task = multipart(inspectors[0], checked, inspector_metadata(scopes[0], addresses[0]), False).json()['id']
    assert owner.get(inbox, params={'source':'inspector'}).json()['items'][0]['preview_url'] is None
    with TestClient(public_app) as citizen:
        signal = int(submit(citizen, metadata(scopes[0], addresses[0])).json()['number'].split('-')[-1])
    dates = {'start':str(today() - timedelta(days=1)), 'end':str(today())}
    for client, endpoint in ((owner,inbox),(inspectors[0],checked)):
        for source, id in (('inspector',task),('signal',signal)):
            assert [item['id'] for item in client.get(endpoint,params={'source':source}).json()['items']] == [id]
            assert client.get(endpoint + '/statistics',params={**dates,'source':source}).json()['total'] == 1
        assert client.get(endpoint,params={'source':'invalid'}).status_code == 422
    for id in (task,signal):
        assert multipart(owner,inbox + f'/{id}/close',{'comment':'Решено администратором','expected_version':1},False).status_code == 200
        assert owner.post(inbox + f'/{id}/archive',json={'archived':True,'expected_version':2}).status_code == 200
    for client, endpoint in ((owner,inbox),(inspectors[0],checked)):
        for source, id in (('inspector',task),('signal',signal)):
            assert client.get(endpoint,params={'source':source}).json()['total'] == 0
            assert [item['id'] for item in client.get(endpoint,params={'source':source,'archived':True}).json()['items']] == [id]
            assert client.get(endpoint + '/statistics',params={**dates,'source':source}).json()['total'] == 1


@pytest.mark.integration
def test_admin_assigns_private_task_to_operator_in_own_organization(workflow):
    owner, scopes, operators, ids, _, inspectors = workflow
    inbox = scopes[0].prefix + '/api/appeals'
    endpoint = inbox + '/internal-tasks'
    response = owner.get(endpoint + '/options')
    assert response.status_code == 200, response.text
    assert ids[0] in [item['id'] for item in response.json()]

    due_date = str(today() + timedelta(days=2))
    body = {'client_id': str(uuid4()), 'subject': 'Проверить урны', 'description': 'Обойти площадки',
            'operator_id': ids[0], 'due_date': due_date}
    assert multipart(operators[0], endpoint, body).status_code == 403
    assert multipart(owner, endpoint, {**body, 'operator_id': 999999}).status_code == 422

    response = multipart(owner, endpoint, body)
    assert response.status_code == 201, response.text
    task_id = response.json()['id']
    assert multipart(owner, endpoint, body).json() == {'id': task_id}
    detail = operators[0].get(inbox + f'/{task_id}').json()
    assert detail['source'] == 'admin' and detail['status'] == 'ASSIGNED'
    assert detail['task']['operator_id'] == ids[0]
    assert detail['task']['due_date'] == due_date
    assert len(detail['photos']) == 1
    assert operators[0].get(detail['photos'][0]['url']).status_code == 200
    assert [item['id'] for item in owner.get(inbox, params={'source': 'admin'}).json()['items']] == [task_id]
    assert owner.get(inbox, params={'source': 'signal'}).json()['total'] == 0
    other_inbox = scopes[1].prefix + '/api/appeals'
    assert operators[1].get(other_inbox + f'/{task_id}').status_code == 404

    inspector = inspectors[0]
    inspector_inbox = f'/api/inspection/organizations/{scopes[0].id}/appeals'
    inspector_detail = inspector_inbox + f'/{task_id}'
    assert inspector.get(inspector_inbox).json()['total'] == 0
    assert inspector.get(inspector_inbox, params={'source': 'admin'}).json()['total'] == 0
    assert inspector.get(inspector_inbox + '/statistics', params={'start': str(today()), 'end': str(today())}).json()['total'] == 0
    assert inspector.get(inspector_inbox + '/notifications').json()['latest_id'] == 0
    assert inspector.get('/api/inspection/appeals/notifications').json()['latest_id'] == 0
    assert inspector.get(inspector_detail).status_code == 404
    assert inspector.get(inspector_detail + '/events').status_code == 404
    assert inspector.get(inspector_detail + '/photos/' + detail['photos'][0]['id']).status_code == 404

    admin_detail = inbox + f'/{task_id}'
    assert multipart(owner, admin_detail + '/close', {'comment': 'Готово', 'expected_version': detail['version']}).status_code == 200
    closed = owner.get(admin_detail).json()
    attachment_id = closed['response_photos'][0]['id']
    assert inspector.get(inspector_detail + '/attachments/' + attachment_id).status_code == 404
    assert owner.post(admin_detail + '/archive', json={'archived': True, 'expected_version': closed['version']}).status_code == 200
    assert inspector.get(inspector_inbox, params={'archived': True}).json()['total'] == 0
    with TestClient(public_app) as citizen:
        assert citizen.get(f'/api/public/appeals/wall/{task_id}').status_code == 404
