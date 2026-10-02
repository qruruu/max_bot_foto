from io import BytesIO
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill
from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.catalog import WORK_TYPES, Status
from app.config import settings
from app.models import District, Photo, User
from app.schemas import PhotoFilters


def filtered(filters: PhotoFilters):
    stmt = select(Photo)
    received_date = cast(func.timezone(settings().app_timezone, Photo.received_at), Date)
    date_field = (
        func.coalesce(Photo.photo_date, received_date) if filters.date_basis == "photo" else received_date
    )
    if filters.day:
        stmt = stmt.where(date_field == filters.day)
    if filters.date_from:
        stmt = stmt.where(date_field >= filters.date_from)
    if filters.date_to:
        stmt = stmt.where(date_field <= filters.date_to)
    if filters.chat_id is not None:
        stmt = stmt.where(Photo.max_chat_id == filters.chat_id)
    if filters.district_id is not None:
        stmt = stmt.where(
            Photo.district_id == filters.district_id if filters.district_id else Photo.district_id.is_(None)
        )
    if filters.work_type:
        stmt = stmt.where(
            Photo.work_type == filters.work_type if filters.work_type != "NONE" else Photo.work_type.is_(None)
        )
    if filters.accepted_only:
        stmt = stmt.where(Photo.status.in_([Status.ACCEPTED, Status.NEEDS_REVIEW]))
    if filters.status:
        stmt = stmt.where(Photo.status == filters.status)
    if filters.operator_id is not None:
        stmt = stmt.where(
            Photo.reviewed_by == filters.operator_id if filters.operator_id else Photo.reviewed_by.is_(None)
        )
    return stmt


def summarize(db: Session, filters: PhotoFilters):
    source = filtered(filters).subquery()
    counts = dict(db.execute(select(source.c.status, func.count()).group_by(source.c.status)).all())
    chats = [
        {"id": cid, "name": name, "count": n}
        for cid, name, n in db.execute(
            select(source.c.max_chat_id, func.max(source.c.chat_name), func.count())
            .group_by(source.c.max_chat_id)
            .order_by(func.count().desc())
        )
    ]
    districts = [
        {"id": did or 0, "name": name or "Не определён", "count": n}
        for did, name, n in db.execute(
            select(source.c.district_id, District.name, func.count())
            .outerjoin(District, District.id == source.c.district_id)
            .group_by(source.c.district_id, District.name)
            .order_by(func.count().desc())
        )
    ]
    works = [
        {
            "id": code or "NONE",
            "name": WORK_TYPES[code][0] if code in WORK_TYPES else "Не определён",
            "count": n,
        }
        for code, n in db.execute(
            select(source.c.work_type, func.count())
            .group_by(source.c.work_type)
            .order_by(func.count().desc())
        )
    ]
    matrix = [
        {"chat_id": cid, "district_id": did or 0, "count": n}
        for cid, did, n in db.execute(
            select(source.c.max_chat_id, source.c.district_id, func.count()).group_by(
                source.c.max_chat_id, source.c.district_id
            )
        )
    ]
    return {
        "total": sum(counts.values()),
        "accepted": counts.get(Status.ACCEPTED, 0) + counts.get(Status.NEEDS_REVIEW, 0),
        "counts": {s: counts.get(s, 0) for s in Status},
        "chats": chats,
        "districts": districts,
        "work_types": works,
        "matrix": matrix,
    }


def photo_dict(photo: Photo, districts: dict[int, str], operators: dict[int, str], detail=False):
    excluded = {"attachment"}
    if not detail:
        excluded |= {"ocr_raw_text", "ocr_date_raw", "ocr_coordinates_raw", "ocr_address_raw", "ai_result"}
    result = {
        col.name: getattr(photo, col.name) for col in Photo.__table__.columns if col.name not in excluded
    }
    result.update(
        district_name=districts.get(photo.district_id),
        operator_name=operators.get(photo.reviewed_by),
        work_type_name=WORK_TYPES[photo.work_type][0] if photo.work_type in WORK_TYPES else None,
        preview_url=f"/api/photos/{photo.id}/preview" if photo.sha256 else None,
    )
    return result


def literal(value):
    # Excel formula injection is prevented for every string, including chat/filename/OCR text.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_excel(db: Session, filters: PhotoFilters) -> bytes:
    wb = Workbook(write_only=True)

    def sheet(name, columns, rows):
        ws = wb.create_sheet(name)
        ws.freeze_panes = "A2"
        cells = []
        for label in columns:
            cell = WriteOnlyCell(ws, value=label)
            cell.font, cell.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="164E47")
            cells.append(cell)
        ws.append(cells)
        count = 1
        for row in rows:
            ws.append([literal(x) for x in row])
            count += 1
        from openpyxl.utils import get_column_letter

        ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{count}"

    districts = dict(db.execute(select(District.id, District.name)).all())
    operators = dict(db.execute(select(User.id, User.name)).all())

    def photo_rows():
        for p in db.scalars(filtered(filters).order_by(Photo.id).execution_options(yield_per=500)):
            yield [
                p.id,
                p.photo_date,
                p.photo_time,
                p.received_at.astimezone(ZoneInfo(settings().app_timezone)).replace(tzinfo=None),
                p.chat_name,
                districts.get(p.district_id),
                WORK_TYPES[p.work_type][0] if p.work_type else None,
                p.latitude,
                p.longitude,
                p.detected_address,
                p.detected_city,
                p.status,
                p.ai_confidence,
                p.work_type_source,
                p.max_message_id,
                p.stored_filename,
                p.yandex_disk_path,
                operators.get(p.reviewed_by),
            ]

    sheet(
        "Все фото",
        [
            "ID",
            "Дата фотографии",
            "Время фотографии",
            "Дата и время получения",
            "Чат",
            "Микрорайон",
            "Вид работы",
            "Latitude",
            "Longitude",
            "Адрес",
            "Город",
            "Статус",
            "AI confidence",
            "Источник классификации",
            "MAX message ID",
            "Имя файла",
            "Путь на Яндекс.Диске",
            "Оператор",
        ],
        photo_rows(),
    )
    report = summarize(db, filters)
    for key, title in [
        ("chats", "По чатам"),
        ("districts", "По микрорайонам"),
        ("work_types", "По видам работ"),
    ]:
        sheet(title, ["Название", "Количество"], ([x["name"], x["count"]] for x in report[key]))
    counts = {(x["chat_id"], x["district_id"]): x["count"] for x in report["matrix"]}
    sheet(
        "Чат × микрорайон",
        ["Чат"] + [d["name"] for d in report["districts"]] + ["Всего"],
        (
            [c["name"]] + [counts.get((c["id"], d["id"]), 0) for d in report["districts"]] + [c["count"]]
            for c in report["chats"]
        ),
    )
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
