"""Human approval of a specific photo's content, separate from automatic acceptance."""

from sqlalchemy import select

from app.models import DayPhotoReview, Photo

SNAPSHOT_FIELDS = (
    "sha256", "photo_date", "photo_time", "latitude", "longitude", "district_id", "work_type", "is_defect", "cohort",
)


def confirmed_condition():
    return select(DayPhotoReview.photo_id).where(
        DayPhotoReview.photo_id == Photo.id,
        Photo.status == "ACCEPTED", Photo.is_spam.is_(False),
        *[getattr(DayPhotoReview, key).is_not_distinct_from(getattr(Photo, key)) for key in SNAPSHOT_FIELDS],
    ).correlate(Photo).exists()
