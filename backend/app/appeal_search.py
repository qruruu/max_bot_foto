"""Search the appeal fields visible to every participant, before pagination."""

from sqlalchemy import String, case, cast, func

from app.config import base_settings
from app.models import CitizenAppeal


def appeal_search(query):
    local_time = func.timezone(base_settings().app_timezone, CitizenAppeal.created_at)
    searchable = func.concat_ws(" ", CitizenAppeal.description, CitizenAppeal.address, CitizenAppeal.place,
        CitizenAppeal.city, CitizenAppeal.organization_name, CitizenAppeal.work_type_name,
        func.concat("ОБ-", func.lpad(cast(CitizenAppeal.id, String), 6, "0")),
        func.to_char(local_time, "DD.MM.YYYY HH24:MI"), func.to_char(local_time, "YYYY-MM-DD"),
        case((CitizenAppeal.status.in_(("RESOLVED", "DECLINED")), CitizenAppeal.public_response), else_=""))
    conditions = []
    for term in query.split():
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append(searchable.ilike("%" + escaped + "%", escape="\\"))
    return conditions
