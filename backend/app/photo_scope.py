"""Keep the operator's workspace in the currently selected intake mode."""

from sqlalchemy import func, select

from app.models import ExchangeState, Photo


def active_cohort_value():
    return func.coalesce(
        select(ExchangeState.intake_cohort).where(ExchangeState.id == 1).scalar_subquery(), "test"
    )


def active_cohort(db):
    return db.scalar(select(active_cohort_value()))


def active_cohort_condition(photo=Photo):
    return photo.cohort == active_cohort_value()
