"""A private folder preference, independent of task state and permissions."""

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.models import CitizenAppeal, PersonalAppealArchive
from app.organization_context import current_organization
from app.schemas import StrictModel


class ArchiveInput(StrictModel):
    archived: bool
    expected_version: int | None = None


def archive_actor(user, *, inspector=False):
    if inspector:
        return "INSPECTOR", str(user.id)
    platform_id = getattr(user, "_platform_user_id", None)
    if platform_id is not None or not current_organization():
        return "OWNER", str(platform_id if platform_id is not None else user.id)
    return "ORGANIZATION_USER", str(user.id)


def archive_conditions(user, *, inspector=False):
    kind, id = archive_actor(user, inspector=inspector)
    return (PersonalAppealArchive.actor_type == kind, PersonalAppealArchive.actor_id == id)


def archived_condition(user, *, inspector=False):
    return select(PersonalAppealArchive.appeal_id).where(
        PersonalAppealArchive.appeal_id == CitizenAppeal.id,
        *archive_conditions(user, inspector=inspector),
    ).exists()


def is_archived(db, appeal, user, *, inspector=False):
    return db.get(PersonalAppealArchive, (appeal.id, *archive_actor(user, inspector=inspector))) is not None


def set_archived(db, appeal, user, archived, *, inspector=False):
    kind, id = archive_actor(user, inspector=inspector)
    if archived:
        db.execute(insert(PersonalAppealArchive).values(appeal_id=appeal.id, actor_type=kind, actor_id=id)
                   .on_conflict_do_nothing())
    else:
        db.execute(delete(PersonalAppealArchive).where(
            PersonalAppealArchive.appeal_id == appeal.id, *archive_conditions(user, inspector=inspector),
        ))
    db.commit()
    return {"ok": True}
