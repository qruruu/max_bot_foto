"""One chronological order for tables, review navigation, return anchors and exports."""

from sqlalchemy import and_, false, or_

from app.models import Photo


def sort_keys(filters):
    if filters.sort_order == "received_desc":
        return [(Photo.received_at, "desc"), (Photo.id, "desc")]
    columns = [Photo.received_at, Photo.id]
    if filters.date_basis == "photo":
        columns = [Photo.photo_date, Photo.photo_time, *columns]
    return [(column, filters.sort_order) for column in columns]


def photo_order(filters):
    # Unknown times follow known times within the day in either direction;
    # unknown dates follow all dated photos. Remaining keys make ties stable.
    return [getattr(column, direction)().nullslast() for column, direction in sort_keys(filters)]


def photo_position(filters, anchor, *, before=False):
    """Seek strictly before/after the anchor in the selected NULLS LAST order."""
    prefix, alternatives = [], []
    for column, direction in sort_keys(filters):
        value = getattr(anchor, column.key)
        if value is None:
            comparison = column.is_not(None) if before else false()
            equal = column.is_(None)
        else:
            ascending = direction == "asc"
            comparison = column > value if ascending != before else column < value
            if not before:
                comparison = or_(comparison, column.is_(None))
            equal = column == value
        alternatives.append(and_(*prefix, comparison))
        prefix.append(equal)
    return or_(*alternatives)
