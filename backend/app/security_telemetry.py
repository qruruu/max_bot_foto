"""Observe data responses without retaining their bodies, URLs, headers or session tokens."""

import ipaddress
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.organization_context import current_organization

MARKER = "METKA_AUDIT_V1 "
ROLES = {"operator", "administrator", "owner", "inspector"}


@dataclass(frozen=True)
class VerifiedActor:
    id: int
    role: str
    organization: str | None


def identify(request, user_id, role, *, login=False):
    """Only authentication code calls this after checking the account and session."""
    if type(user_id) is not int or user_id <= 0 or role not in ROLES:
        return
    organization = current_organization()
    request.state.metka_verified_actor = VerifiedActor(
        user_id, role, str(UUID(str(organization.id))) if organization else None
    )
    if login:
        request.state.metka_login_complete = True


def resource(path, method):
    if path == "/api/health":
        return "health"
    if method == "POST" and path in {
        "/api/auth/login",
        "/api/auth/choose-organization",
        "/api/inspection/login",
    }:
        return "login"
    if method not in {"GET", "HEAD"}:
        return None
    if path.startswith("/api/public/appeals") or re.fullmatch(r"/a/[0-9]+(?:/card[.]jpg)?", path):
        return "public_media" if re.search(r"/(photos|results)/|/card[.]jpg$", path) else "public_records"
    if not path.startswith("/api/"):
        return None
    if path.endswith("/original"):
        return "original"
    if path.endswith((".xlsx", "/xlsx", "/print")):
        return "report_export"
    if path.endswith("/preview"):
        return "preview"
    if re.search(r"/(attachments|photos)/[0-9]+$", path) and "appeals" in path:
        return "appeal_media"
    if path.startswith(
        (
            "/api/inspection/organizations/",
            "/api/photos",
            "/api/appeals",
            "/api/platform/appeals",
            "/api/daily-reports",
            "/api/reports",
        )
    ):
        return "private_records"
    return None


def emit(row):
    sys.stdout.write(MARKER + json.dumps(row, separators=(",", ":")) + "\n")
    sys.stdout.flush()


class SecurityTelemetry:
    """Pure ASGI observer: count accepted body bytes; do not consume/buffer a stream."""

    def __init__(self, app, emit_record=None):
        self.app = app
        self.emit = emit_record or emit
        self.dropped = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        category = resource(scope["path"], scope["method"])
        if category is None:
            return await self.app(scope, receive, send)
        status, sent, complete, measured = None, 0, False, True
        failed = False
        state = scope.setdefault("state", {})

        async def observed_send(message):
            nonlocal status, sent, complete, measured
            await send(message)
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body":
                sent += len(message.get("body", b""))
                complete = not message.get("more_body", False)
            elif message["type"] == "http.response.pathsend":
                measured, complete = False, True

        try:
            return await self.app(scope, receive, observed_send)
        except BaseException:
            failed = True
            raise
        finally:
            actor = state.get("metka_verified_actor")
            if not isinstance(actor, VerifiedActor):
                actor = None
            if failed or not complete:
                outcome = "interrupted"
            elif status in {401, 403}:
                outcome = "denied"
            elif status == 429:
                outcome = "limited"
            elif status == 404:
                outcome = "not_found"
            elif status is not None and 300 <= status < 400:
                outcome = "link_issued" if category == "original" else "redirect"
            elif status is not None and 200 <= status < 300:
                outcome = "served" if measured else "unmeasured"
                if category == "login":
                    outcome = (
                        "login_verified"
                        if actor and state.get("metka_login_complete") is True
                        else "login_unverified"
                    )
            else:
                outcome = "error"
            try:
                ip = str(ipaddress.ip_address(scope["client"][0])) if scope.get("client") else None
            except ValueError:
                ip = None
            row = dict(
                schema=1,
                id=str(uuid4()),
                at=datetime.now(UTC).isoformat(),
                resource=category,
                method=scope["method"],
                status=status,
                response_bytes=sent,
                measured=measured,
                complete=complete and not failed,
                outcome=outcome,
                ip=ip,
                actor_id=actor.id if actor else None,
                role=actor.role if actor else None,
                organization=actor.organization if actor else None,
                observer_dropped=self.dropped,
            )
            try:
                self.emit(row)
            except (OSError, ValueError):
                self.dropped += 1
