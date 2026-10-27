"""Daily contract letters, isolated by organization database and test/production cohort."""

from copy import deepcopy
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select, text

from app.auth import Db, check_permission, require_permission
from app.catalog import NON_WORK_STATUSES
from app.chat_access import chat_condition
from app.daily_report_calendar import season_for, work_period
from app.daily_report_schemas import (
    ReportingConfig,
    ReportingCreateInput,
    ReportingDocument,
    ReportingLine,
    ReportingSaveInput,
    ReportingSettingsInput,
    ReportingVersionInput,
)
from app.domain import audit, now
from app.models import (
    DailyReport,
    DailyReportingSettings,
    DailyReportRevision,
    District,
    Organization,
    Photo,
    User,
    WorkType,
)
from app.organization_context import current_organization, workspace_url
from app.permissions import Permission
from app.photo_scope import active_cohort

router = APIRouter(prefix="/api/daily-reports", tags=["daily-reports"])
Reader = Annotated[User, Depends(require_permission(Permission.DAILY_REPORTS_VIEW))]
Editor = Annotated[User, Depends(require_permission(Permission.DAILY_REPORTS_EDIT))]
Configurator = Annotated[User, Depends(require_permission(Permission.DAILY_REPORTS_CONFIGURE))]


def checked_report(db, id, version=None, lock=False):
    stmt = select(DailyReport).where(DailyReport.id == id, DailyReport.cohort == active_cohort(db))
    row = db.scalar(stmt.with_for_update() if lock else stmt)
    if not row:
        raise HTTPException(404, "Отчёт не найден в текущем режиме")
    if version is not None and row.version != version:
        raise HTTPException(409, "Отчёт изменён в другом окне. Обновите его перед сохранением.")
    return row


def config_lookups(config):
    return ({w.id: w for w in config.works}, {a.id: a for a in config.areas})


def catalog_names(db, config):
    """Use company district names for setup/new drafts; approved snapshots stay frozen."""
    config = config.model_copy(deep=True)
    districts = dict(db.execute(select(District.id, District.name)).all())
    for area in config.areas:
        area.district_ids = list(dict.fromkeys(area.district_ids))
        if area.district_ids and all(id in districts for id in area.district_ids):
            area.name = ", ".join(districts[id] for id in area.district_ids)
    return config


def check_document(document, config):
    works, areas = config_lookups(config)
    assignments = {(w.id, a.area_id) for w in config.works for a in w.assignments}
    for kind in ("fact", "plan"):
        rows = getattr(document, kind)
        keys = [(r.work_id, r.area_id) for r in rows]
        if len(set(keys)) != len(keys) or any(key not in assignments for key in keys):
            raise HTTPException(422, "Строки должны ссылаться на разные работы и территории из настройки отчёта")
        for row in rows:
            if row.work_id not in works or row.area_id not in areas:
                raise HTTPException(422, "Работа или территория не найдена")
        if set(getattr(document, kind + "_events")) - works.keys():
            raise HTTPException(422, "Неизвестное событие в календаре")


def issues_for(document, config):
    problems = []
    if not config.profile.company_name.strip() or not any(v.strip() for v in config.profile.recipient) or not config.contracts:
        problems.append("Заполните организацию, адресата и хотя бы один контракт")
    for kind, label in (("fact", "Факт"), ("plan", "План")):
        if not getattr(document, kind + "_season") and any(w.season != "all" for w in config.works):
            problems.append(label + ": выберите сезон или задайте его границы в настройках")
        works, areas = config_lookups(config)
        for row in getattr(document, kind):
            name = f"{label}: {works[row.work_id].name} — {areas[row.area_id].name}"
            if row.decision == "pending":
                problems.append(name + ": примите решение")
            elif row.decision == "include" and (row.quantity is None or row.quantity <= 0):
                problems.append(name + ": укажите объём больше нуля или выберите «Без объёма»")
            if row.decision == "include" and works[row.work_id].unit == "уточнить":
                problems.append(name + ": уточните единицу измерения в настройке нового отчёта")
    return problems


def previous_facts(db, cohort, before, exclude=None):
    stmt = select(DailyReport).where(DailyReport.cohort == cohort, DailyReport.approved.is_not(None),
                                     DailyReport.day <= before + timedelta(days=1))
    if exclude is not None:
        stmt = stmt.where(DailyReport.id != exclude)
    return [(r.day - timedelta(days=1), ReportingDocument.model_validate(r.approved)) for r in db.scalars(stmt)]


def build_lines(day, config, season, events, past):
    result = []
    for work in config.works:
        period = work_period(day, work, season, events)
        if period is None:
            continue
        first, last = period
        for assignment in work.assignments:
            facts = [line for d, doc in past if first <= d <= last and d < day for line in doc.fact
                     if line.work_id == work.id and line.area_id == assignment.area_id and line.decision == "include"]
            done = round(sum(line.quantity or 0 for line in facts), 3)
            if work.recurrence not in {"daily", "event", "dates"} and (
                any(line.cycle_complete for line in facts)
                or (assignment.quantity is not None and assignment.quantity > 0 and done >= assignment.quantity)
            ):
                continue
            quantity = assignment.quantity
            if quantity is not None and work.recurrence not in {"daily", "event", "dates", "interval"}:
                quantity = max(0, round(quantity - done, 3))
            result.append(ReportingLine(work_id=work.id, area_id=assignment.area_id,
                                        quantity=quantity, resources=assignment.resources))
    return result


def evidence_selection(day, cohort, user):
    return select(Photo).where(Photo.photo_date == day, Photo.cohort == cohort,
                               Photo.preview_removed_at.is_(None), Photo.is_spam.is_(False),
                               Photo.status.not_in(NON_WORK_STATUSES), chat_condition(user))


def evidence_for(db, user, day, config, cohort):
    rows = list(db.scalars(evidence_selection(day, cohort, user)))
    works, areas = config_lookups(config)
    counts, unmatched = {}, 0
    signatures = {}
    for photo in rows:
        # An unrecognized photo date must never be replaced by its receipt date in a contract letter.
        if photo.photo_date != day:
            continue
        signatures[str(photo.id)] = photo.version
        matches = [(w.id, a.area_id) for w in works.values() for a in w.assignments
                   if photo.work_type in w.photo_codes and photo.district_id in areas[a.area_id].district_ids]
        if not matches:
            unmatched += 1
        for work_id, area_id in matches:
            entry = counts.setdefault(work_id + ":" + area_id, {"total": 0, "needs_review": 0})
            entry["total"] += 1
            entry["needs_review"] += photo.status != "ACCEPTED"
    return {"rows": counts, "unmatched": unmatched, "total": len(signatures), "signatures": signatures}


def revision(db, report, user, action):
    db.add(DailyReportRevision(report_id=report.id, version=report.version, action=action,
                               document={"document": deepcopy(report.draft), "config": deepcopy(report.config),
                                         "letter_numbers": dict(report.letter_numbers)}, author_id=user.id))
    audit(db, user.id, "DAILY_REPORT_" + action, "daily_report", report.id, None,
          {"day": str(report.day), "version": report.version, "cohort": report.cohort})


def report_dict(db, report, user):
    config = ReportingConfig.model_validate(report.config)
    document = ReportingDocument.model_validate(report.draft)
    evidence = evidence_for(db, user, report.day - timedelta(days=1), config, report.cohort)
    old = report.evidence.get("signatures", {})
    current = evidence["signatures"]
    return {"id": report.id, "day": report.day, "fact_day": report.day - timedelta(days=1),
            "cohort": report.cohort, "version": report.version, "config": report.config,
            "document": report.draft, "approved": report.approved is not None,
            "changed": report.approved is not None and report.approved_version != report.version,
            "approved_at": report.approved_at, "letter_numbers": report.letter_numbers,
            "issues": issues_for(document, config), "evidence": evidence,
            "new_photos": len(current.keys() - old.keys()) if report.approved else 0,
            "changed_photos": sum(current.get(k) != v for k, v in old.items()) if report.approved else 0}


@router.get("/settings")
def get_settings(db: Db, user: Reader):
    row = db.get(DailyReportingSettings, 1)
    config = ReportingConfig.model_validate(row.config) if row else ReportingConfig()
    if not row and (organization := current_organization()):
        from app.organization_registry import control_session
        config.profile.company_name = config.profile.short_name = organization.name
        with control_session() as control:
            record = control.get(Organization, organization.id)
            config.profile.city = record.city or "" if record else ""
    return {"version": row.version if row else 0, "config": catalog_names(db, config).model_dump()}


@router.put("/settings")
def save_settings(body: ReportingSettingsInput, db: Db, user: Configurator):
    db.execute(text("SELECT pg_advisory_xact_lock(7021, 1)"))
    row = db.scalar(select(DailyReportingSettings).where(DailyReportingSettings.id == 1).with_for_update())
    if (row.version if row else 0) != body.version:
        raise HTTPException(409, "Настройки изменены в другом окне. Обновите страницу.")
    district_ids = {id for a in body.config.areas for id in a.district_ids}
    codes = {code for w in body.config.works for code in w.photo_codes}
    if district_ids - set(db.scalars(select(District.id))) or codes - set(db.scalars(select(WorkType.code))):
        raise HTTPException(422, "Выбран неизвестный микрорайон или вид фотографии")
    body.config = catalog_names(db, body.config)
    if row:
        previous = ReportingConfig.model_validate(row.config)
        approved_documents = list(db.scalars(select(DailyReport.approved).where(DailyReport.approved.is_not(None))))
        if approved_documents:
            used_work_ids = {r["work_id"] for doc in approved_documents for r in doc["fact"] if r["decision"] == "include"}
            old_units = {w.id: w.unit for w in previous.works}
            if any(w.id in used_work_ids and w.id in old_units and w.unit != old_units[w.id] for w in body.config.works):
                raise HTTPException(422, "Для новой единицы измерения добавьте новый вид работы: по прежнему уже есть утверждённые отчёты")
        for contract in body.config.contracts:
            old = next((c for c in previous.contracts if c.id == contract.id and c.prefix == contract.prefix), None)
            if old and contract.next_number < old.next_number:
                raise HTTPException(422, "Следующий номер письма нельзя уменьшать: он мог быть уже использован")
        row.config, row.version = body.config.model_dump(), row.version + 1
    else:
        row = DailyReportingSettings(id=1, version=1, config=body.config.model_dump())
        db.add(row)
    audit(db, user.id, "DAILY_REPORT_SETTINGS", "daily_reporting_settings", 1, None, {"version": row.version})
    db.commit()
    return {"version": row.version, "config": row.config}


@router.get("")
def list_reports(db: Db, user: Reader, limit: int = Query(default=60, ge=1, le=366)):
    return [{"id": r.id, "day": r.day, "version": r.version, "approved": r.approved is not None,
             "changed": r.approved is not None and r.approved_version != r.version,
             "approved_at": r.approved_at, "letter_numbers": r.letter_numbers}
            for r in db.scalars(select(DailyReport).where(DailyReport.cohort == active_cohort(db))
                                .order_by(DailyReport.day.desc()).limit(limit))]


@router.post("", status_code=201)
def create_report(body: ReportingCreateInput, db: Db, user: Editor):
    cohort = active_cohort(db)
    db.execute(text("SELECT pg_advisory_xact_lock(7022, :day)"), {"day": body.day.toordinal()})
    existing = db.scalar(select(DailyReport).where(DailyReport.day == body.day, DailyReport.cohort == cohort))
    if existing:
        return report_dict(db, existing, user)
    settings = db.get(DailyReportingSettings, 1)
    if settings is None:
        raise HTTPException(422, "Сначала сохраните настройку отчётности организации")
    config = catalog_names(db, ReportingConfig.model_validate(settings.config))
    if not config.contracts or not config.works:
        raise HTTPException(422, "Добавьте контракты, территории и работы")
    fact_day = body.day - timedelta(days=1)
    past = previous_facts(db, cohort, body.day)
    fact_season, plan_season = season_for(fact_day, config), season_for(body.day, config)
    document = ReportingDocument(fact_season=fact_season, plan_season=plan_season,
        fact=build_lines(fact_day, config, fact_season, [], past),
        plan=build_lines(body.day, config, plan_season, [], past))
    previous = db.scalar(select(DailyReport).where(DailyReport.day == fact_day,
                         DailyReport.cohort == cohort, DailyReport.approved.is_not(None)))
    if previous:
        available = {(w.id, a.area_id) for w in config.works for a in w.assignments}
        document.fact = [ReportingLine(**{**line, "decision": "pending", "cycle_complete": False})
                         for line in previous.approved["plan"] if line["decision"] in {"include", "info"}
                         and (line["work_id"], line["area_id"]) in available]
    report = DailyReport(day=body.day, cohort=cohort, config=config.model_dump(), draft=document.model_dump(),
                         version=1, letter_numbers={}, evidence={})
    db.add(report)
    db.flush()
    revision(db, report, user, "CREATED")
    db.commit()
    return report_dict(db, report, user)


@router.get("/{id}")
def get_report(id: int, db: Db, user: Reader):
    return report_dict(db, checked_report(db, id), user)


@router.put("/{id}")
def save_report(id: int, body: ReportingSaveInput, db: Db, user: Editor):
    report = checked_report(db, id, body.version, lock=True)
    config = ReportingConfig.model_validate(report.config)
    check_document(body.document, config)
    report.draft, report.version = body.document.model_dump(), report.version + 1
    revision(db, report, user, "SAVED")
    db.commit()
    return report_dict(db, report, user)


@router.post("/{id}/calendar")
def refresh_calendar(id: int, body: ReportingSaveInput, db: Db, user: Editor):
    report = checked_report(db, id, body.version, lock=True)
    config = ReportingConfig.model_validate(report.config)
    document = body.document
    check_document(document, config)
    past = previous_facts(db, report.cohort, report.day, exclude=report.id)
    for kind, day in (("fact", report.day - timedelta(days=1)), ("plan", report.day)):
        current = {(r.work_id, r.area_id): r for r in getattr(document, kind)}
        generated = build_lines(day, config, getattr(document, kind + "_season"), getattr(document, kind + "_events"), past)
        for line in generated:
            current.setdefault((line.work_id, line.area_id), line)
        setattr(document, kind, list(current.values()))
    report.draft, report.version = document.model_dump(), report.version + 1
    revision(db, report, user, "CALENDAR")
    db.commit()
    return report_dict(db, report, user)


@router.post("/{id}/approve")
def approve_report(id: int, body: ReportingVersionInput, db: Db, user: Editor):
    # One organization-wide transaction protects limits and letter counters across different dates.
    db.execute(text("SELECT pg_advisory_xact_lock(7021, 1)"))
    report = checked_report(db, id, body.version, lock=True)
    if report.approved_version == report.version:
        return report_dict(db, report, user)
    config = ReportingConfig.model_validate(report.config)
    document = ReportingDocument.model_validate(report.draft)
    check_document(document, config)
    issues = issues_for(document, config)
    if issues:
        raise HTTPException(422, {"message": "Проверьте незаполненные строки", "issues": issues})
    past = previous_facts(db, report.cohort, date(report.day.year + 1, 1, 1), exclude=report.id)
    year = (report.day - timedelta(days=1)).year
    for work in config.works:
        for assignment in work.assignments:
            if assignment.annual_limit is None:
                continue
            used = sum(r.quantity or 0 for d, doc in past if d.year == year for r in doc.fact
                       if r.work_id == work.id and r.area_id == assignment.area_id and r.decision == "include")
            added = sum(r.quantity or 0 for r in document.fact if r.work_id == work.id
                        and r.area_id == assignment.area_id and r.decision == "include")
            if round(used + added, 3) > assignment.annual_limit:
                raise HTTPException(422, f"Превышен годовой лимит: {work.name}. Уже учтено {used:g}, добавлено {added:g} {work.unit}")
    numbers = dict(report.letter_numbers)
    if any(c.id not in numbers for c in config.contracts):
        settings = db.scalar(select(DailyReportingSettings).where(DailyReportingSettings.id == 1).with_for_update())
        current = ReportingConfig.model_validate(settings.config)
        issued = {value for record in db.scalars(select(DailyReport.letter_numbers).where(
            DailyReport.cohort == "production", DailyReport.approved.is_not(None))) for value in record.values()}
        for contract in config.contracts:
            if contract.id in numbers:
                continue
            counter = next((c for c in current.contracts if c.id == contract.id), None)
            if counter is None:
                raise HTTPException(409, "Контракт удалён из настройки. Верните его перед первым утверждением отчёта.")
            # Test letters have their own date-based numbers and cannot consume production counters.
            numbers[contract.id] = ("ТЕСТ-" + contract.prefix + report.day.strftime("%Y%m%d")) if report.cohort == "test" else f"{counter.prefix}{counter.next_number:03}"
            if report.cohort == "production":
                # Removing and later restoring a contract must not reuse an issued outgoing number.
                while numbers[contract.id] in issued:
                    counter.next_number += 1
                    numbers[contract.id] = f"{counter.prefix}{counter.next_number:03}"
                issued.add(numbers[contract.id])
                counter.next_number += 1
        if report.cohort == "production":
            settings.config, settings.version = current.model_dump(), settings.version + 1
    report.letter_numbers = numbers
    report.approved, report.approved_version = deepcopy(report.draft), report.version
    report.approved_config = deepcopy(report.config)
    report.approved_at, report.approved_by = now(), user.id
    report.evidence = evidence_for(db, user, report.day - timedelta(days=1), config, report.cohort)
    revision(db, report, user, "APPROVED")
    db.commit()
    return report_dict(db, report, user)


@router.post("/{id}/rebuild")
def rebuild_report(id: int, body: ReportingVersionInput, db: Db, user: Editor):
    report = checked_report(db, id, body.version, lock=True)
    settings = db.get(DailyReportingSettings, 1)
    config = catalog_names(db, ReportingConfig.model_validate(settings.config))
    old_config = ReportingConfig.model_validate(report.config)
    old_works, old_areas = config_lookups(old_config)
    document = ReportingDocument.model_validate(report.draft)
    available = {(w.id, a.area_id) for w in config.works for a in w.assignments}
    new_works, new_areas = config_lookups(config)
    for kind in ("fact", "plan"):
        kept = []
        for line in getattr(document, kind):
            if (line.work_id, line.area_id) not in available:
                continue
            if old_works[line.work_id].unit != new_works[line.work_id].unit or old_areas[line.area_id] != new_areas[line.area_id]:
                line.quantity, line.decision = None, "pending"
            kept.append(line)
        setattr(document, kind, kept)
        setattr(document, kind + "_events", [w for w in getattr(document, kind + "_events") if w in new_works])
    report.config, report.draft = config.model_dump(), document.model_dump()
    report.version += 1
    revision(db, report, user, "REBUILT")
    db.commit()
    return report_dict(db, report, user)


@router.get("/{id}/photos")
def report_photos(id: int, work_id: str, area_id: str, db: Db, user: Reader,
                  page: int = Query(default=1, ge=1)):
    check_permission(user, Permission.PHOTOS_VIEW)
    report = checked_report(db, id)
    config = ReportingConfig.model_validate(report.config)
    works, areas = config_lookups(config)
    if work_id not in works or area_id not in areas or not any(a.area_id == area_id for a in works[work_id].assignments):
        raise HTTPException(404, "Работа не найдена в отчёте")
    stmt = evidence_selection(report.day - timedelta(days=1), report.cohort, user).where(
        Photo.work_type.in_(works[work_id].photo_codes), Photo.district_id.in_(areas[area_id].district_ids))
    from sqlalchemy import func
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    return {"total": total, "page": page,
            "items": [{"id": p.id, "status": p.status, "preview_url": workspace_url(f"/api/photos/{p.id}/preview") if p.sha256 else None}
                      for p in db.scalars(stmt.order_by(Photo.id).offset((page - 1) * 60).limit(60))]}


@router.get("/{id}/history")
def report_history(id: int, db: Db, user: Reader):
    checked_report(db, id)
    return [{"version": r.version, "action": r.action, "at": r.at, "author": name, "document": r.document}
            for r, name in db.execute(select(DailyReportRevision, User.name).join(User, User.id == DailyReportRevision.author_id)
                                     .where(DailyReportRevision.report_id == id).order_by(DailyReportRevision.id.desc()))]


@router.get("/{id}/xlsx")
def report_xlsx(id: int, db: Db, user: Reader, draft: bool = False):
    from app.daily_report_export import export_xlsx
    report = checked_report(db, id)
    if not draft and report.approved is None:
        raise HTTPException(409, "Сначала утвердите отчёт или скачайте черновик")
    content = export_xlsx(report, draft=draft)
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="daily-report-{report.day}.xlsx"'})


@router.get("/{id}/print", response_class=HTMLResponse)
def report_print(id: int, db: Db, user: Reader, draft: bool = False):
    from app.daily_report_export import export_html
    report = checked_report(db, id)
    if not draft and report.approved is None:
        raise HTTPException(409, "Сначала утвердите отчёт или откройте черновик")
    return HTMLResponse(export_html(report, draft=draft))
