"""Human approval of a specific photo's content, separate from automatic acceptance."""

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased

from app.models import DayClosure, DayClosureChat, DayPhotoReview, Photo

SNAPSHOT_FIELDS = (
    "sha256", "photo_date", "photo_time", "latitude", "longitude", "district_id", "work_type", "is_defect", "cohort",
)


def confirmed_condition():
    return select(DayPhotoReview.photo_id).where(
        DayPhotoReview.photo_id == Photo.id,
        Photo.status == "ACCEPTED", Photo.is_spam.is_(False),
        *[getattr(DayPhotoReview, key).is_not_distinct_from(getattr(Photo, key)) for key in SNAPSHOT_FIELDS],
    ).correlate(Photo).exists()


def last_confirmation_value():
    """A per-photo cutoff includes empty chats covered by the original closure."""
    reviewed_photo = aliased(Photo)
    legacy_scope = select(DayPhotoReview.photo_id).join(
        reviewed_photo, reviewed_photo.id == DayPhotoReview.photo_id
    ).where(
        DayPhotoReview.closure_id == DayClosure.id,
        reviewed_photo.max_chat_id == Photo.max_chat_id, DayPhotoReview.cohort == Photo.cohort,
    ).correlate(DayClosure, Photo).exists()
    explicit_scope = select(DayClosureChat.closure_id).where(
        DayClosureChat.closure_id == DayClosure.id, DayClosureChat.max_chat_id == Photo.max_chat_id,
    ).correlate(DayClosure, Photo).exists()
    return select(func.max(DayClosure.confirmed_at)).where(
        DayClosure.day == Photo.photo_date,
        or_(and_(DayClosure.cohort == Photo.cohort, or_(DayClosure.all_chats.is_(True), explicit_scope)),
            and_(DayClosure.cohort.is_(None), legacy_scope)),
    ).correlate(Photo).scalar_subquery()
