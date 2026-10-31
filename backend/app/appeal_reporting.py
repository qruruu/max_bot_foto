"""Staff-only filters and statistics. No public serializers use this module."""
from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.appeal_statuses import is_final
from app.config import base_settings
from app.domain import now
from app.models import AppealTask, CitizenAppeal

DeadlineFilter = Literal['any', 'none', 'overdue', 'today', 'week']


def today():
    return now().astimezone(ZoneInfo(base_settings().app_timezone)).date()


def latest_id():
    other = aliased(AppealTask)
    return select(func.max(other.id)).where(other.appeal_id == CitizenAppeal.id).correlate(CitizenAppeal).scalar_subquery()


def filters(category='', operator='', deadline='any', organization=''):
    conditions = []
    if category:
        conditions.append(CitizenAppeal.category == ('' if category == '__none__' else category))
    if organization:
        conditions.append(CitizenAppeal.organization_id == organization)
    task_conditions = [AppealTask.id == latest_id()]
    if operator:
        try:
            org, user_id = operator.rsplit(':', 1)
            user_id = int(user_id)
        except (ValueError, TypeError):
            raise HTTPException(422, 'Выберите исполнителя из списка') from None
        conditions.append(CitizenAppeal.organization_id == org)
        task_conditions.append(AppealTask.operator_id == user_id)
    if deadline == 'none':
        conditions.append(~select(AppealTask.id).where(AppealTask.id == latest_id(), AppealTask.due_date.is_not(None)).exists())
    elif deadline != 'any':
        task_conditions.extend([AppealTask.status.in_(('ASSIGNED', 'IN_PROGRESS')), AppealTask.due_date.is_not(None)])
        conditions.extend([CitizenAppeal.resolved_at.is_(None), CitizenAppeal.archived_at.is_(None),
                           CitizenAppeal.status.in_(('ASSIGNED', 'IN_PROGRESS'))])
        if deadline == 'overdue':
            task_conditions.append(AppealTask.due_date < today())
        elif deadline == 'today':
            task_conditions.append(AppealTask.due_date == today())
        elif deadline == 'week':
            task_conditions.extend([AppealTask.due_date >= today(), AppealTask.due_date <= today() + timedelta(days=7)])
    if operator or deadline not in ('any', 'none'):
        conditions.append(select(AppealTask.id).where(*task_conditions).exists())
    return conditions


def options(db, conditions):
    works = db.execute(select(CitizenAppeal.category, CitizenAppeal.work_type_name).where(*conditions).distinct()).all()
    people = db.execute(select(CitizenAppeal.organization_id, AppealTask.operator_id, AppealTask.operator_name)
                        .join(AppealTask, AppealTask.id == latest_id()).where(*conditions).distinct()).all()
    organizations = db.execute(select(CitizenAppeal.organization_id, CitizenAppeal.organization_name)
                               .where(*conditions).distinct()).all()
    work_options = {code or '__none__': {'code': code or '__none__', 'name': name or 'Не указан'} for code, name in works}
    return {'work_types': sorted(work_options.values(), key=lambda x: x['name']),
            'operators': sorted([{'value': f'{org}:{id}', 'name': name} for org, id, name in people], key=lambda x: x['name']),
            'organizations': [{'id': id, 'name': name} for id, name in organizations if id]}


def task_summaries(db, appeals):
    ids = [a.id for a in appeals]
    tasks = {t.appeal_id: t for t in db.scalars(select(AppealTask).where(AppealTask.appeal_id.in_(ids)).order_by(AppealTask.id))} if ids else {}
    result = {}
    for a in appeals:
        task = tasks.get(a.id)
        result[a.id] = {'operator_name': task.operator_name if task else '', 'operator_id': task.operator_id if task else None,
                        'due_date': task.due_date if task else None,
                        'overdue': bool(task and task.due_date and task.due_date < today() and task.status in ('ASSIGNED', 'IN_PROGRESS')
                                        and a.status in ('ASSIGNED', 'IN_PROGRESS')
                                        and not is_final(a) and not a.archived_at)}
    return result


def statistics(db, conditions, start: date, end: date, category='', operator='', organization='', task_operator_id=None):
    if start > end or end == date.max or (end - start).days > 1096:
        raise HTTPException(422, 'Выберите период до трёх лет с корректными датами')
    zone = ZoneInfo(base_settings().app_timezone)
    bounds = [CitizenAppeal.created_at >= datetime.combine(start, time.min, zone),
              CitizenAppeal.created_at < datetime.combine(end + timedelta(days=1), time.min, zone)]
    scope = [*conditions, *bounds, *filters(category, operator, organization=organization)]
    # Select only reporting columns; never load image bytes, contacts or private notes.
    fields = (CitizenAppeal.id, CitizenAppeal.organization_id, CitizenAppeal.organization_name, CitizenAppeal.status,
              CitizenAppeal.resolved_at, CitizenAppeal.created_at, CitizenAppeal.archived_at,
              CitizenAppeal.category, CitizenAppeal.work_type_name)
    appeals = list(db.execute(select(*fields).where(*scope)))
    ids = [a.id for a in appeals]
    tasks = list(db.execute(select(AppealTask.id, AppealTask.appeal_id, AppealTask.operator_id, AppealTask.operator_name,
                                  AppealTask.status, AppealTask.created_at, AppealTask.finished_at, AppealTask.due_date)
                            .where(AppealTask.appeal_id.in_(ids)).order_by(AppealTask.id))) if ids else []
    # Operator-filtered reports include only that operator's own assignments, never another tenant's same numeric ID.
    if operator:
        selected_id = int(operator.rsplit(':', 1)[1])
        tasks = [t for t in tasks if t.operator_id == selected_id]
    if task_operator_id is not None:
        tasks = [t for t in tasks if t.operator_id == task_operator_id]
    by_id = {a.id: a for a in appeals}
    latest = {t.appeal_id: t.id for t in tasks}
    people = {}
    timed = []
    for t in tasks:
        a = by_id[t.appeal_id]
        key = f'{a.organization_id}:{t.operator_id}'
        person = people.setdefault(key, {'key': key, 'name': t.operator_name, 'organization_name': a.organization_name,
                                         'total': 0, 'completed': 0, 'active': 0, 'overdue': 0, 'other': 0, '_days': []})
        person['total'] += 1
        active = (latest[t.appeal_id] == t.id and t.status in ('ASSIGNED', 'IN_PROGRESS')
                  and a.status in ('ASSIGNED', 'IN_PROGRESS') and not is_final(a) and not a.archived_at)
        overdue = bool(active and t.due_date and t.due_date < today())
        person['active'] += int(active and not overdue)
        person['overdue'] += int(overdue)
        person['completed'] += int(t.status == 'COMPLETED')
        person['other'] += int(not active and t.status != 'COMPLETED')
        if t.status == 'COMPLETED' and t.finished_at:
            person['_days'].append(max(0, (t.finished_at - t.created_at).total_seconds() / 86400))
            if t.due_date:
                timed.append(t.finished_at.astimezone(zone).date() <= t.due_date)
    for person in people.values():
        days = person.pop('_days')
        person['average_days'] = round(sum(days) / len(days), 1) if days else None
    work_counts = Counter(a.category for a in appeals)
    work_names = {a.category: a.work_type_name or 'Не указан' for a in appeals}
    status_counts = Counter(a.status for a in appeals)
    resolved = [a for a in appeals if a.status == 'RESOLVED']
    durations = [max(0, (a.resolved_at - a.created_at).total_seconds() / 86400) for a in resolved if a.resolved_at]
    return {'start': start, 'end': end, 'timezone': str(zone), 'total': len(appeals), 'completed': len(resolved),
            'active': sum(not is_final(a) for a in appeals), 'overdue': sum(p['overdue'] for p in people.values()),
            'average_days': round(sum(durations) / len(durations), 1) if durations else None,
            'on_time_percent': round(sum(timed) * 100 / len(timed), 1) if timed else None, 'timed_tasks': len(timed),
            'operators': sorted(people.values(), key=lambda p: (-p['total'], p['name'])),
            'work_types': [{'code': code, 'name': work_names[code], 'count': count} for code, count in work_counts.most_common()],
            'statuses': [{'code': code, 'count': count} for code, count in status_counts.items()],
            'options': options(db, conditions)}
