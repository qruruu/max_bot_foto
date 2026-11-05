"""Queue gallery previews before they occupy a database connection or worker thread."""

import re
from asyncio import Semaphore

PREVIEW_PATH = re.compile(r"(?:/org/[0-9a-f-]{36})?/api/photos/[0-9]+/preview")


class PreviewAdmission:
    def __init__(self, app):
        self.app = app
        # Reserve capacity in the ten-slot platform pool for page and login requests.
        self.slots = Semaphore(6)

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] == "http"
            and scope["method"] in {"GET", "HEAD"}
            and PREVIEW_PATH.fullmatch(scope["path"])
        ):
            async with self.slots:
                return await self.app(scope, receive, send)
        return await self.app(scope, receive, send)
