import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_appeal_workflow import metadata, multipart, submit
from test_appeal_workflow import workflow as workflow
from test_inspections import inspection as inspection
from test_organizations import companies as companies

from app.appeal_reporting import today
from app.appeals_public import app as public_app
from app.domain import now
from app.models import AppealTask, CitizenAppeal
from app.organization_registry import control_session

pytestmark = pytest.mark.integration


def created_id(citizen, scope, address):
    response = submit(citizen, metadata(scope, address))
    assert response.status_code == 201, response.text
    return int(response.json()['number'].split('-')[-1])


def test_deadline_permissions_version_history_reassignment_and_public_privacy(workflow):
    owner, scopes, operators, ids, addresses, inspectors = workflow
    base = scopes[0].prefix + '/api/appeals'
    with TestClient(public_app) as citizen:
        id = created_id(citizen, scopes[0], addresses[0])
        endpoint = base + f'/{id}'
        due = (today() + timedelta(days=3)).isoformat()
        body = {'due_date': due, 'expected_version': 1}
        assert owner.post(endpoint + '/deadline', json=body).status_code == 409
        assert owner.post(endpoint + '/assign', json={'operator_id': ids[0], 'expected_version': 1}).status_code == 200
        body['expected_version'] = 2
        assert operators[0].post(endpoint + '/deadline', json=body).status_code == 403
        assert inspectors[0].post(f'/api/inspection/organizations/{scopes[0].id}/appeals/{id}/deadline', json=body).status_code in (404, 405)
        past = {**body, 'due_date': (today() - timedelta(days=1)).isoformat()}
        assert owner.post(endpoint + '/deadline', json=past).status_code == 422
        assert owner.post(endpoint + '/deadline', json=body).status_code == 200
        assert owner.post(endpoint + '/deadline', json=body).status_code == 409
        assert operators[0].get(endpoint).json()['task']['due_date'] == due
        assert owner.get(base, params={'deadline': 'week'}).json()['total'] == 1
        assert owner.get(base, params={'deadline': 'none'}).json()['total'] == 0
        assert owner.get(base, params={'operator': f'{scopes[1].id}:{ids[1]}'}).json()['total'] == 0
        assert 'Срок исполнения' in json.dumps(owner.get(endpoint + '/events').json(), ensure_ascii=False)
        assert owner.post(endpoint + '/deadline', json={'due_date': None, 'expected_version': 3}).status_code == 200
        assert owner.post(endpoint + '/deadline', json={'due_date': due, 'expected_version': 4}).status_code == 200
        assert owner.post(endpoint + '/assign', json={'operator_id': ids[0], 'expected_version': 5}).status_code == 200
        detail = owner.get(endpoint).json()
        assert detail['task']['due_date'] is None
        assert detail['task_history'][1]['due_date'] == due
        assert detail['task_history'][1]['status'] == 'CANCELLED'
        assert detail['task_history'][1]['finished_at']
        for public in (citizen.get(f'/api/public/appeals/wall/{id}').json(), citizen.get('/api/public/appeals/wall', params={'city': 'Сургут'}).json()):
            assert all(key not in json.dumps(public) for key in ('due_date', 'finished_at', 'operator_name', 'overdue'))
        response = multipart(operators[0], endpoint + '/result', {'status': 'COMPLETED', 'comment': 'Убрано', 'expected_version': 6})
        assert response.status_code == 200
        assert owner.get(endpoint).json()['task']['finished_at']
        assert owner.post(endpoint + '/deadline', json={'due_date': due, 'expected_version': 7}).status_code == 409


def test_reports_use_real_tasks_scope_dates_and_late_results(workflow):
    owner, scopes, operators, ids, addresses, inspectors = workflow
    base = scopes[0].prefix + '/api/appeals'
    with TestClient(public_app) as citizen:
        own = [created_id(citizen, scopes[0], addresses[0]) for _ in range(3)]
        foreign = created_id(citizen, scopes[1], addresses[1])
    for id in own[:2]:
        assert owner.post(base + f'/{id}/assign', json={'operator_id': ids[0], 'expected_version': 1}).status_code == 200
    assert owner.post(scopes[1].prefix + f'/api/appeals/{foreign}/assign', json={'operator_id': ids[1], 'expected_version': 1}).status_code == 200
    endpoint = base + f'/{own[0]}'
    assert multipart(operators[0], endpoint + '/result', {'status': 'COMPLETED', 'comment': 'Сделано', 'expected_version': 2}).status_code == 200
    assert multipart(owner, endpoint + '/close', {'comment': 'Работа выполнена', 'expected_version': 3}, False).status_code == 200
    with control_session() as db:
        completed = db.scalar(select(AppealTask).where(AppealTask.appeal_id == own[0]))
        completed.due_date = today() - timedelta(days=1)  # historical deadline, completion today is late
        late = db.scalar(select(AppealTask).where(AppealTask.appeal_id == own[1]))
        late.due_date = today() - timedelta(days=1)
        # Boundary: an older complaint is not part of this created-date cohort.
        db.get(CitizenAppeal, own[2]).created_at = now() - timedelta(days=60)
        db.commit()
    params = {'start': (today() - timedelta(days=29)).isoformat(), 'end': today().isoformat()}
    result = owner.get(base + '/statistics', params=params)
    assert result.status_code == 200, result.text
    stats = result.json()
    assert (stats['total'], stats['completed'], stats['active'], stats['overdue']) == (2, 1, 1, 1)
    assert stats['timed_tasks'] == 1 and stats['on_time_percent'] == 0
    assert stats['operators'][0]['total'] == 2
    assert stats['operators'][0]['completed'] == 1
    assert stats['operators'][0]['overdue'] == 1
    assert sum(w['count'] for w in stats['work_types']) == 2
    assert sum(s['count'] for s in stats['statuses']) == 2
    own_stats = operators[0].get(base + '/statistics', params=params).json()
    assert own_stats['total'] == 2
    assert owner.get(base, params={'deadline': 'overdue'}).json()['items'][0]['id'] == own[1]
    checked = f'/api/inspection/organizations/{scopes[0].id}/appeals'
    assert inspectors[0].get(checked + '/statistics', params=params).json()['total'] == 2
    assert inspectors[1].get(checked + '/statistics', params=params).status_code == 404
    assert inspectors[0].get(checked, params={'deadline': 'overdue'}).json()['total'] == 1
    assert 'private-phone' not in json.dumps(stats) and 'owner_note' not in json.dumps(stats)
    assert owner.get(base + '/statistics', params={**params, 'start': '2030-01-01'}).status_code == 422
    empty = owner.get(base + '/statistics', params={**params, 'category': 'MISSING'}).json()
    assert empty['total'] == 0 and empty['average_days'] is None and empty['on_time_percent'] is None
    assert owner.get(base + '/statistics', params={**params, 'operator': f'{scopes[1].id}:{ids[1]}'}).json()['total'] == 0
