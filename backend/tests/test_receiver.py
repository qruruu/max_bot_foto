"""The MAX checkpoint must advance only with durable photo intake."""

from sqlalchemy import func, select
from test_integration import event, setup_chat

from app.config import settings
from app.models import Inbox, Job, MaxReceiverState, Photo
from app.receiver import poll_once


class MaxPage:
    def __init__(self, updates, marker=42, subscriptions=None):
        self.updates, self.marker = updates, marker
        self.subscriptions = subscriptions or []
        self.markers = []

    def request(self, method, path, **kwargs):
        assert method == "GET"
        if path == "/subscriptions":
            return {"subscriptions": self.subscriptions}
        assert path == "/updates"
        self.markers.append(kwargs["params"].get("marker"))
        return {"updates": self.updates, "marker": self.marker}


def configure(monkeypatch):
    monkeypatch.setenv("MAX_UPDATE_MODE", "polling")
    monkeypatch.setenv("MAX_BOT_TOKEN", "isolated-test-token")
    settings.cache_clear()


def test_repeated_max_page_is_durable_and_does_not_duplicate_photos(db, monkeypatch):
    configure(monkeypatch)
    setup_chat(db)
    client = MaxPage([event()])
    assert poll_once(client) and poll_once(client)
    db.expire_all()
    assert client.markers == [None, 42]
    assert db.scalar(select(func.count()).select_from(Photo)) == 1
    assert db.scalar(select(func.count()).select_from(Inbox)) == 1
    assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "BATCH")) == 1
    state = db.get(MaxReceiverState, 1)
    assert state.marker == 42 and state.inbox_received == 1 and state.events_received == 2


def test_failed_page_rolls_back_intake_and_checkpoint_then_recovers(db, monkeypatch):
    configure(monkeypatch)
    setup_chat(db)
    assert poll_once(MaxPage([], marker=10))
    malformed = event("bad")
    malformed["message"]["body"]["attachments"] = [None]
    assert not poll_once(MaxPage([event("good"), malformed], marker=20))
    db.expire_all()
    assert db.get(MaxReceiverState, 1).marker == 10
    assert db.scalar(select(func.count()).select_from(Photo)) == 0
    assert db.scalar(select(func.count()).select_from(Job)) == 0
    assert poll_once(MaxPage([event("good"), event("bad")], marker=20))
    db.expire_all()
    assert db.get(MaxReceiverState, 1).marker == 20
    assert db.get(MaxReceiverState, 1).last_error is None
    assert db.scalar(select(func.count()).select_from(Photo)) == 2


def test_poller_does_not_compete_with_a_registered_webhook(db, monkeypatch):
    configure(monkeypatch)
    client = MaxPage([event()], subscriptions=[{"url": "https://example.invalid/webhook"}])
    assert not poll_once(client)
    assert not client.markers
    db.expire_all()
    assert db.get(MaxReceiverState, 1).last_error == "MAX_WEBHOOK_ACTIVE"
