import json

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings


class RequestSizeLimit:
    """Bound the complete body before multipart parsing can spool unbounded data."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return
        # Allow a small bounded allowance for multipart headers and boundaries.
        maximum = get_settings().max_upload_bytes + 65536
        content_type = dict(scope["headers"]).get(b"content-type", b"").lower()
        is_json = content_type.startswith(b"application/json")
        if is_json:
            maximum = min(maximum, 2 * 1024 * 1024)
        headers = dict(scope["headers"])
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(
                scope, receive, send
            )
            return
        if declared < 0:
            await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(
                scope, receive, send
            )
            return
        chunks: list[bytes] = []
        length = 0
        if declared <= maximum:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                length += len(chunk)
                if length > maximum:
                    break
                chunks.append(chunk)
                if not message.get("more_body", False):
                    break
        if declared > maximum or length > maximum:
            await JSONResponse({"detail": "Request body too large"}, status_code=413)(
                scope, receive, send
            )
            return
        body = b"".join(chunks)
        if is_json and body:
            try:
                json.loads(body)
            except (ValueError, UnicodeError, RecursionError):
                await JSONResponse({"detail": "Invalid JSON body"}, status_code=400)(
                    scope, receive, send
                )
                return
        consumed = False

        async def bounded_receive() -> Message:
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
