from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.catalog import NON_WORK_STATUSES, Status
from app.models import MaxSender, Photo
from app.reports import filtered
from app.schemas import PhotoFilters


def photo_filter_counts(db: Session, filters: PhotoFilters, *, include_spam: bool = False, user=None):
    """Count each alternative with the other dimensions and date range still applied."""
    result = {}
    for name, column, missing in [
        ("work_type", Photo.work_type, "NONE"),
        ("district_id", Photo.district_id, "0"),
        ("chat_id", Photo.max_chat_id, "0"),
        ("operator_id", Photo.reviewed_by, "0"),
        ("sender_id", Photo.sender_id, "0"),
    ]:
        selection = filters.model_copy(update={name: None})
        rows = db.execute(
            filtered(selection, user).with_only_columns(column, func.count()).group_by(column)
        ).all()
        values = {str(value) if value is not None else missing: count for value, count in rows}
        result[name] = {"total": sum(values.values()), "values": values}
        if name == "sender_id":
            ids = [value for value, _ in rows if value is not None]
            # Only resolve senders observed in this authorized selection, never the global directory.
            names = dict(db.execute(
                select(MaxSender.sender_id, MaxSender.name).where(MaxSender.sender_id.in_(ids))
            ).all()) if ids else {}
            result[name]["options"] = [
                {"value": str(id), "name": names.get(id)}
                for id in sorted(ids, key=lambda id: (id not in names, (names.get(id) or "").casefold(), id))
            ]

    # Alternatives remain visible even when they are omitted from normal sorting.
    selection = filters.model_copy(update={"status": None, "accepted_only": False, "work_only": False})
    values = dict(db.execute(
        filtered(selection, user).with_only_columns(Photo.status, func.count()).group_by(Photo.status)
    ).all())
    total = sum(count for status, count in values.items() if not filters.work_only or status not in NON_WORK_STATUSES)
    values["ACCEPTED_ALL"] = values.get(Status.ACCEPTED, 0) + values.get(Status.NEEDS_REVIEW, 0)
    if include_spam:
        spam = filters.model_copy(update={"status": Status.SPAM, "accepted_only": False})
        values[Status.SPAM] = db.scalar(
            filtered(spam, user).with_only_columns(func.count(), maintain_column_froms=True)
        )
    else:
        values.pop(Status.SPAM, None)
    result["status"] = {"total": total, "values": values}
    return result
