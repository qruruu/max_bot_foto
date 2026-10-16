"""Display reported client metadata; never use it as an authentication factor."""

import logging
import re
from datetime import timedelta
from ipaddress import ip_address

from sqlalchemy import func, or_, update
from sqlalchemy.exc import SQLAlchemyError

from app.models import LoginSession

log = logging.getLogger(__name__)


def record_session_activity(db):
    activity = db.info.pop("session_activity")
    # As on Session.close(), discard any uncommitted handler work before auxiliary metadata.
    db.rollback()
    try:
        instant = activity["at"]
        db.execute(
            update(LoginSession)
            .where(
                LoginSession.token_hash == activity["token_hash"],
                LoginSession.expires_at > instant,
                or_(
                    LoginSession.last_seen_at.is_(None),
                    LoginSession.last_seen_at < instant - timedelta(minutes=1),
                ),
            )
            .values(
                last_seen_at=instant,
                user_agent=func.coalesce(LoginSession.user_agent, activity.get("user_agent")),
                ip_address=func.coalesce(activity.get("ip_address"), LoginSession.ip_address),
            )
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        log.warning("session_activity_error=%s", type(exc).__name__)


def client_address(request):
    # Respect the ASGI server's trusted proxy configuration, not arbitrary forwarded headers.
    try:
        return str(ip_address(request.client.host)) if request.client else None
    except ValueError:
        return None


def client_description(user_agent):
    ua = user_agent or ""
    if "iPad" in ua:
        device, kind, os = "iPad", "tablet", "iPadOS"
    elif "iPhone" in ua or "iPod" in ua:
        device, kind, os = "iPhone", "phone", "iOS"
    elif "Android" in ua:
        kind = "phone" if "Mobile" in ua else "tablet"
        device, os = "Устройство Android", "Android"
    elif "Windows" in ua:
        device, kind, os = "Компьютер Windows", "desktop", "Windows"
    elif "Macintosh" in ua or "Mac OS X" in ua:
        device, kind, os = "Mac", "desktop", "macOS"
    elif "CrOS" in ua:
        device, kind, os = "Chromebook", "desktop", "ChromeOS"
    elif "Linux" in ua:
        device, kind, os = "Компьютер Linux", "desktop", "Linux"
    else:
        device, kind, os = "Устройство не определено", "unknown", None
    browser = "Браузер не определён"
    for name, pattern in [
        ("Edge", r"(?:Edg|EdgA|EdgiOS)/([\d.]+)"),
        ("Opera", r"(?:OPR|OPiOS)/([\d.]+)"),
        ("Яндекс Браузер", r"YaBrowser/([\d.]+)"),
        ("Firefox", r"(?:Firefox|FxiOS)/([\d.]+)"),
        ("Chrome", r"(?:Chrome|CriOS)/([\d.]+)"),
        ("Safari", r"Version/([\d.]+).*Safari/"),
    ]:
        match = re.search(pattern, ua)
        if match:
            browser = f"{name} {match[1]}"
            break
    return {"device": device, "device_type": kind, "os": os, "browser": browser}


def session_dict(session, current_id):
    return {
        "id": session.id,
        "current": session.id == current_id,
        "created_at": session.created_at,
        "last_seen_at": session.last_seen_at,
        "expires_at": session.expires_at,
        "ip_address": session.ip_address,
        **client_description(session.user_agent),
    }
