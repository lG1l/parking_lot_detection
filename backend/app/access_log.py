import ipaddress
import logging

from fastapi import Request
from sqlalchemy import text

from app.db import get_engine

logger = logging.getLogger(__name__)

LOGIN = "login"
ISSUE_UPLOAD_LINK = "issue_upload_link"
VIEW_STILL = "view_still"
VIEW_CLIP = "view_clip"
PIN_INCIDENT = "pin_incident"


def client_ip(request: Request) -> str | None:
    # 프록시 헤더(X-Forwarded-For)는 위조할 수 있어 믿지 않고 접속한 쪽 주소를 쓴다
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None


def write_access_log(
    action: str, request: Request, user_id: int | None = None, video_id: int | None = None
) -> None:
    """법정 기록 한 행. 실패해도 API는 성공으로 답하고 서버 로그에만 남긴다 (D-53)."""
    try:
        with get_engine().begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO access_logs (user_id, video_id, action, requested_ip) "
                    "VALUES (:user_id, :video_id, :action, :ip)"
                ),
                {
                    "user_id": user_id,
                    "video_id": video_id,
                    "action": action,
                    "ip": client_ip(request),
                },
            )
    except Exception as exc:  # noqa: BLE001 - 기록 실패가 API를 막으면 안 된다
        logger.error("access log write failed: action=%s error=%s", action, type(exc).__name__)
