from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_appeal_workflow import metadata, submit
from test_appeal_workflow import workflow as workflow
from test_inspections import inspection as inspection
from test_organizations import companies as companies

from app.appeals_public import app as public_app
from app.models import AppealPhoto, CitizenAppeal
from app.organization_registry import control_session

pytestmark = pytest.mark.integration


def test_staff_searches_all_pages_dates_and_archive_with_existing_access_boundaries(workflow):
    owner, scopes, operators, operator_ids, addresses, inspectors = workflow
    with TestClient(public_app) as citizen:
        first = submit(citizen, {**metadata(scopes[0], addresses[0]), 'description': 'Мусор возле фонаря'})
        second = submit(citizen, {**metadata(scopes[0], addresses[0]), 'description': 'Сломана калитка'})
        foreign = submit(citizen, {**metadata(scopes[1], addresses[1]), 'description': 'Мусор возле фонаря. Чужойсекрет'})
        assert first.status_code == second.status_code == foreign.status_code == 201
    id = int(first.json()['number'].split('-')[-1])
    inbox = scopes[0].prefix + '/api/appeals'
    checked = f'/api/inspection/organizations/{scopes[0].id}/appeals'
    assert owner.post(inbox + f'/{id}/assign', json={'operator_id': operator_ids[0], 'expected_version': 1}).status_code == 200
    with control_session() as db:
        appeal = db.get(CitizenAppeal, id)
        appeal.created_at = datetime(2026, 10, 20, 22, 30, tzinfo=UTC)
        appeal.owner_note, appeal.contact, appeal.public_response = 'Служебныйсекрет', 'Личныйконтакт', 'Черновикответа'
        db.get(CitizenAppeal, int(second.json()['number'].split('-')[-1])).created_at = datetime(2026, 10, 22, 7, 30, tzinfo=UTC)
        source = db.scalar(select(AppealPhoto).where(AppealPhoto.appeal_id == id))
        photo_values = {key: getattr(source, key) for key in (
            'original', 'stamped', 'preview', 'captured_at', 'position_at', 'latitude', 'longitude', 'accuracy', 'width', 'height')}
        # The matching complaint is older than a whole page of other records.
        for index in range(20):
            noise = CitizenAppeal(organization_id=scopes[0].id, organization_name=scopes[0].name, city='Сургут',
                address='Другой сквер', place='Вход', category='BIN_EMPTYING', description=f'Другая проблема {index}',
                photo_count=1, status='NEW', owner_note='', contact='', version=1,
                created_at=datetime(2026, 11, 28, 7, 30, tzinfo=UTC))
            db.add(noise)
            db.flush()
            db.add(AppealPhoto(id=str(uuid4()), appeal_id=noise.id, position=0, **photo_values))
        db.commit()
    assert id not in [item['id'] for item in owner.get(inbox).json()['items']]
    assert owner.post(inbox + f'/{id}/comments', json={'client_id': str(uuid4()), 'comment': 'Секретчата'}).status_code == 201

    readers = [(owner, inbox), (operators[0], inbox), (inspectors[0], checked)]
    def search(client, path, q, **params):
        response = client.get(path, params={'q': q, **params})
        assert response.status_code == 200, response.text
        return response.json()
    for client, path in readers:
        for query in ('МУСОР фонаря', '21 10 2026', '21.10.2026', '2026-10-21', first.json()['number']):
            result = search(client, path, query)
            assert result['total'] == 1 and [item['id'] for item in result['items']] == [id], (path, query, result['total'])
        for hidden in ('Чужойсекрет', 'Служебныйсекрет', 'Личныйконтакт', 'Черновикответа', 'Секретчата', '%', '_'):
            assert search(client, path, hidden)['total'] == 0
        assert search(client, path, 'фонаря', status='NEW')['total'] == 0
        assert client.get(path, params={'q': 'x' * 201}).status_code == 422
    assert search(owner, '/api/platform/appeals', 'фонаря')['total'] == 2
    assert search(operators[0], inbox, 'калитка')['total'] == 0
    assert inspectors[1].get(checked, params={'q': 'фонаря'}).status_code == 404
    assert owner.patch(inbox + f'/{id}', json={'status': 'SPAM', 'owner_note': '', 'expected_version': 2}).status_code == 200
    assert owner.post(inbox + f'/{id}/archive', json={'archived': True, 'expected_version': 3}).status_code == 200
    for client, path in readers:
        assert search(client, path, 'фонаря')['total'] == 0
        assert search(client, path, 'фонаря', archived=True, status='SPAM')['total'] == 1
        assert search(client, path, 'фонаря', archived=True, status='NEW')['total'] == 0
