"""A request/job has exactly one workspace; it never falls back to another company's data."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class OrganizationScope:
    id: str
    name: str
    database_url: str = field(repr=False)
    data_dir: Path
    owner_user_id: int
    yandex_disk_token: str | None = field(default=None, repr=False)

    @property
    def prefix(self):
        return f"/org/{self.id}"


_organization: ContextVar[OrganizationScope | None] = ContextVar("organization", default=None)


def current_organization():
    return _organization.get()


@contextmanager
def organization_scope(organization):
    token = _organization.set(organization)
    try:
        yield organization
    finally:
        _organization.reset(token)


def workspace_url(path):
    organization = current_organization()
    return organization.prefix + path if organization else path
