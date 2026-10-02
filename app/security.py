import secrets

from starlette.responses import JSONResponse


class AuthBoundary:
    def __init__(self, app, token):
        self.app = app
        self.token = token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        path = scope["path"]
        public = scope["method"] == "GET" and path in ("/healthz", "/readyz")
        headers = dict(scope["headers"])
        authorized = secrets.compare_digest(
            headers.get(b"authorization", b""), b"Bearer " + self.token
        )
        if not public and not authorized:
            await JSONResponse(
                {"detail": "Authentication required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
            return
        if path.startswith("/engine") and scope["method"] not in ("GET", "HEAD"):
            await JSONResponse(
                {"detail": "Use the validated /runs API"}, status_code=405
            )(scope, receive, send)
            return
        await self.app(scope, receive, send)
