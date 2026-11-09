"""Store one coarse presence timestamp per authenticated staff account."""

from datetime import timedelta

from sqlalchemy import or_, update

from app.domain import now


def mark_present(db, account):
    instant = now()
    cutoff = instant - timedelta(seconds=50)
    if account.last_seen_at is not None and account.last_seen_at >= cutoff:
        return
    model = type(account)
    db.execute(update(model).where(
        model.id == account.id, model.active.is_(True),
        or_(model.last_seen_at.is_(None), model.last_seen_at < cutoff),
    ).values(last_seen_at=instant).execution_options(synchronize_session=False))
    db.commit()
