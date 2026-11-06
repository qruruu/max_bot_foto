"""Private task documents and chat screenshots; every download rechecks its audience."""
from io import BytesIO
from pathlib import PurePath
from urllib.parse import quote
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException, Response
from sqlalchemy import select

from app.appeal_images import MAX_PHOTO_BYTES, prepare_upload
from app.models import AppealEvent, AppealFile

MAX_DOCUMENT_BYTES = 25 * 1024 * 1024


def prepare_document(content, name):
    name = PurePath(name.replace("\\", "/")).name[:200]
    suffix = PurePath(name).suffix.lower()
    types = {".pdf": "application/pdf", ".doc": "application/msword", ".xls": "application/vnd.ms-excel",
             ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    if not content or len(content) > MAX_DOCUMENT_BYTES or suffix not in types:
        raise HTTPException(422, "Выберите Word, Excel или PDF размером до 25 МБ")
    valid = content.startswith(b"%PDF-") if suffix == ".pdf" else content.startswith(bytes.fromhex("d0cf11e0a1b11ae1"))
    if suffix in {".docx", ".xlsx"}:
        try:
            with ZipFile(BytesIO(content)) as archive:
                names = archive.namelist()
                valid = "[Content_Types].xml" in names and ("word/document.xml" if suffix == ".docx" else "xl/workbook.xml") in names
                # Macro-bearing and encrypted containers are outside the accepted formats.
                valid = valid and not any("vbaproject" in n.lower() for n in names)
        except BadZipFile:
            valid = False
    if not valid:
        raise HTTPException(422, "Содержимое файла не соответствует формату Word, Excel или PDF")
    return {"name": name, "media_type": types[suffix], "content": content}


def prepare_screenshot(content):
    if len(content) > MAX_PHOTO_BYTES:
        raise HTTPException(422, "Скриншот слишком большой")
    image = prepare_upload(content, min_side=1)
    return {"name": "screenshot.jpg", "media_type": "image/jpeg", "content": image["original"]}


def store_files(db, appeal, files, event_id=None):
    for file in files:
        db.add(AppealFile(id=str(uuid4()), appeal_id=appeal.id, event_id=event_id, **file))


def file_dict(file, url):
    return {"id": file.id, "name": file.name, "media_type": file.media_type,
            "url": url(f"/{file.appeal_id}/files/{file.id}")}


def file_response(db, appeal, file_id, *, user=None, inspector=False):
    file = db.get(AppealFile, str(file_id))
    if not file or file.appeal_id != appeal.id:
        raise HTTPException(404)
    if file.event_id:
        from app.appeal_events import visible_conditions
        event = db.scalar(select(AppealEvent).where(AppealEvent.id == file.event_id,
                          *visible_conditions(appeal, user=user, inspector=inspector)))
        if event is None:
            raise HTTPException(404)
    disposition = "inline" if file.media_type == "image/jpeg" else "attachment"
    return Response(file.content, media_type=file.media_type, headers={"Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(file.name, safe='')}"})
