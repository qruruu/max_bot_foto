import asyncio
import json
from types import SimpleNamespace

import pytest

from app.organization_context import OrganizationScope, organization_scope
from app.security_telemetry import SecurityTelemetry, VerifiedActor, identify


def exercise(
    *,
    status=200,
    actor=None,
    chunks=(b"PRIVATE_CONTENT",),
    fail=False,
    path="/api/export.xlsx",
    method="GET",
    state=None,
    pathsend=False,
):
    records, delivered = [], []
    scope = dict(
        type="http",
        path=path,
        method=method,
        client=("198.51.100.10", 1234),
        query_string=b"token=PRIVATE_TOKEN",
        headers=[(b"cookie", b"PRIVATE_COOKIE"), (b"x-user-id", b"999")],
        state=state or {},
    )

    async def app(scope, receive, send):
        if actor:
            scope["state"]["metka_verified_actor"] = actor
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"location", b"https://private.example/PRIVATE_TOKEN")],
            }
        )
        if pathsend:
            await send({"type": "http.response.pathsend", "path": "PRIVATE_FILE"})
            return
        for i, chunk in enumerate(chunks):
            await send({"type": "http.response.body", "body": chunk, "more_body": i < len(chunks) - 1})

    async def send(message):
        if fail and message["type"] == "http.response.body" and delivered:
            raise OSError("disconnected")
        delivered.append(message)

    observer = SecurityTelemetry(app, emit_record=records.append)
    if fail:
        with pytest.raises(OSError):
            asyncio.run(observer(scope, None, send))
    else:
        asyncio.run(observer(scope, None, send))
    return records, delivered


def test_verified_identity_bytes_and_no_sensitive_content():
    actor = VerifiedActor(7, "owner", "11111111-1111-4111-8111-111111111111")
    rows, delivered = exercise(actor=actor, chunks=(b"PRIVATE_CONTENT", b"0123"))
    row = rows[0]
    assert row["actor_id"] == 7 and row["role"] == "owner" and row["organization"] == actor.organization
    assert row["response_bytes"] == 19 and row["complete"] and row["outcome"] == "served"
    assert [m.get("body") for m in delivered[1:]] == [b"PRIVATE_CONTENT", b"0123"]
    assert all(
        s not in json.dumps(row)
        for s in ["PRIVATE_CONTENT", "PRIVATE_TOKEN", "PRIVATE_COOKIE", "999", "export.xlsx"]
    )


def test_unverified_claims_denied_redirect_and_disconnect_are_distinct():
    row = exercise(status=403, state={"metka_verified_actor": {"id": 999}})[0][0]
    assert row["actor_id"] is None and row["outcome"] == "denied"
    row = exercise(status=302, path="/api/photos/7/original")[0][0]
    assert row["outcome"] == "link_issued" and row["response_bytes"] != 999999
    row = exercise(fail=True)[0][0]
    assert row["outcome"] == "interrupted" and row["response_bytes"] == 0 and not row["complete"]
    row = exercise(pathsend=True)[0][0]
    assert row["outcome"] == "unmeasured" and not row["measured"]
    assert exercise(path="/api/health")[0][0]["resource"] == "health"
    assert not exercise(path="/assets/not-data.js")[0]


def test_login_choice_is_not_a_verified_login():
    row = exercise(path="/api/auth/login", method="POST")[0][0]
    assert row["outcome"] == "login_unverified"
    row = exercise(
        path="/api/auth/login",
        method="POST",
        actor=VerifiedActor(1, "operator", None),
        state={"metka_login_complete": True},
    )[0][0]
    assert row["outcome"] == "login_verified"


def test_verified_actor_uses_resolved_workspace_and_only_safe_ids(tmp_path):
    req = SimpleNamespace(state=SimpleNamespace())
    org = OrganizationScope(
        "11111111-1111-4111-8111-111111111111", "Private organization", "PRIVATE_DB", tmp_path, 1
    )
    with organization_scope(org):
        identify(req, 9, "operator")
    assert req.state.metka_verified_actor == VerifiedActor(9, "operator", org.id)
    req2 = SimpleNamespace(state=SimpleNamespace())
    identify(req2, "PRIVATE_LOGIN", "operator")
    assert not hasattr(req2.state, "metka_verified_actor")


def test_logging_failure_does_not_block_the_response():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b"ok"})

    async def send(message):
        pass

    def broken(row):
        raise OSError("log unavailable")

    observer = SecurityTelemetry(app, emit_record=broken)
    asyncio.run(observer({"type": "http", "method": "GET", "path": "/api/health", "state": {}}, None, send))
    assert observer.dropped == 1


def test_real_authenticated_export_emits_verified_actor(admin, capsys):
    from app.security_telemetry import MARKER

    capsys.readouterr()
    response = admin.get("/api/export.xlsx?private_marker=PRIVATE_QUERY", headers={"X-User-Id": "999"})
    assert response.status_code == 200
    rows = [
        json.loads(line[len(MARKER) :])
        for line in capsys.readouterr().out.splitlines()
        if line.startswith(MARKER)
    ]
    row = next(row for row in rows if row["resource"] == "report_export")
    assert row["actor_id"] == 1 and row["role"] == "administrator"
    assert row["response_bytes"] == len(response.content) and row["outcome"] == "served"
    assert "PRIVATE_QUERY" not in json.dumps(row)


def test_real_unauthorized_export_has_no_invented_actor(client, capsys):
    from app.security_telemetry import MARKER

    response = client.get("/api/export.xlsx", headers={"X-User-Id": "999"})
    assert response.status_code == 401
    rows = [
        json.loads(line[len(MARKER) :])
        for line in capsys.readouterr().out.splitlines()
        if line.startswith(MARKER)
    ]
    row = next(row for row in rows if row["resource"] == "report_export")
    assert row["actor_id"] is None and row["outcome"] == "denied"
