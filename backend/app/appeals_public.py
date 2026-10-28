"""Public deployment exposes no operator authentication, documentation or private API."""

from fastapi import FastAPI, HTTPException
from starlette.responses import JSONResponse

from app import appeal_workflow  # noqa: F401 - registers map intake and public wall
from app.appeal_images import MAX_PHOTO_BYTES, MAX_PHOTOS
from app.appeals import public_router


class AppealBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        maximum = MAX_PHOTO_BYTES * MAX_PHOTOS + 128 * 1024
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Неверный размер запроса"}, 400)(scope, receive, send)
        if length > maximum:
            return await JSONResponse({"detail": "Слишком большой объём фотографий"}, 413)(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > maximum:
                raise HTTPException(413, "Слишком большой объём фотографий")
            return message

        return await self.app(scope, limited_receive, send)


app = FastAPI(title="Обращения граждан", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(public_router)
app.add_middleware(AppealBodyLimit)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                             "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"})
    return response


@app.get("/api/health")
def health():
    return {"ok": True}
