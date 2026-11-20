"""Download published response photos after the caller checks appeal access."""

from functools import partial
from tempfile import SpooledTemporaryFile
from typing import Annotated
from uuid import UUID
from zipfile import ZipFile

from fastapi import HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.appeal_images import MAX_PHOTOS
from app.models import AppealAttachment

ResponsePhotoIds = Annotated[list[UUID], Query(min_length=1, max_length=MAX_PHOTOS)]


def response_photo_download(db: Session, appeal_id: int, photo_ids: list[UUID]):
    ids = list(dict.fromkeys(photo_ids))
    name = f"appeal-{appeal_id}-response"

    def load(photo_id: UUID) -> bytes:
        content = db.scalar(select(AppealAttachment.content).where(
            AppealAttachment.id == str(photo_id), AppealAttachment.appeal_id == appeal_id, AppealAttachment.published,
        ))
        if content is None:
            raise HTTPException(404, "Фотография ответа недоступна")
        return content

    def headers(filename: str) -> dict[str, str]:
        return {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        }

    if len(ids) == 1:
        return Response(load(ids[0]), media_type="image/jpeg", headers=headers(f"{name}-{ids[0]}.jpg"))

    archive = SpooledTemporaryFile(max_size=2 * 1024 * 1024)
    try:
        with ZipFile(archive, "w") as zip_file:
            for photo_id in ids:
                zip_file.writestr(f"{name}-{photo_id}.jpg", load(photo_id))
        size = archive.tell()
        archive.seek(0)
    except BaseException:
        archive.close()
        raise

    return StreamingResponse(
        iter(partial(archive.read, 64 * 1024), b""),
        media_type="application/zip",
        headers={**headers(f"{name}.zip"), "Content-Length": str(size)},
        background=BackgroundTask(archive.close),
    )
