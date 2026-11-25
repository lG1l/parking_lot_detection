"""CloudFront를 거친 요청만 받는다 (D-340 4번).

CloudFront는 원본(EC2)으로 보내는 모든 요청에 비밀 헤더 X-Origin-Verify를 붙인다.
값이 맞지 않으면 EC2에 직접 들어온 요청으로 보고 403으로 막는다. 채팅 WebSocket도 같다.
"""

import hmac

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

HEADER = b"x-origin-verify"


class OriginGuard:
    def __init__(self, app: ASGIApp, secret: str):
        self.app = app
        self.secret = secret.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        got = dict(scope["headers"]).get(HEADER, b"")
        if hmac.compare_digest(got, self.secret):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            # accept 전에 닫으면 서버가 HTTP 403으로 답한다
            await send({"type": "websocket.close", "code": 1008})
            return
        response = JSONResponse(
            {"error": {"code": "FORBIDDEN", "message": "direct access is not allowed"}},
            status_code=403,
        )
        await response(scope, receive, send)
