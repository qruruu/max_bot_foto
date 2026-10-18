from sqlalchemy import func
from sqlalchemy.orm import Session

from app.catalog import Status
from app.models import Photo
from app.reports import filtered
from app.schemas import PhotoFilters


def photo_filter_counts(db: Session, filters: PhotoFilters, *, include_spam: bool = False):
    """Count each alternative with the other dimensions and date range still applied."""
    result = {}
    for name, column, missing in [
        ("work_type", Photo.work_type, "NONE"),
        ("district_id", Photo.district_id, "0"),
        ("chat_id", Photo.max_chat_id, "0"),
        ("operator_id", Photo.reviewed_by, "0"),
    ]:
        selection = filters.model_copy(update={name: None})
        rows = db.execute(
            filtered(selection).with_only_columns(column, func.count()).group_by(column)
        ).all()
        values = {str(value) if value is not None else missing: count for value, count in rows}
        result[name] = {"total": sum(values.values()), "values": values}

    selection = filters.model_copy(update={"status": None, "accepted_only": False})
    values = dict(db.execute(
        filtered(selection).with_only_columns(Photo.status, func.count()).group_by(Photo.status)
    ).all())
    total = sum(values.values())
    values["ACCEPTED_ALL"] = values.get(Status.ACCEPTED, 0) + values.get(Status.NEEDS_REVIEW, 0)
    if include_spam:
        spam = filters.model_copy(update={"status": Status.SPAM, "accepted_only": False})
        values[Status.SPAM] = db.scalar(
            filtered(spam).with_only_columns(func.count(), maintain_column_froms=True)
        )
    else:
        values.pop(Status.SPAM, None)
    result["status"] = {"total": total, "values": values}
    return result
