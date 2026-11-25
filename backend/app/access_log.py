import ipaddress
import logging

from fastapi import Request
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine

logger = logging.getLogger(__name__)

LOGIN = "login"
LOOKUP_INVITEE = "lookup_invitee"
CREATE_CASE = "create_case"
ACCEPT_CASE = "accept_case"
VIEW_STILL = "view_still"
VIEW_CLIP = "view_clip"
PIN_INCIDENT = "pin_incident"
AGREE_VIEWING = "agree_viewing"
VIEW_INCIDENT_TIMES = "view_incident_times"


def client_ip(request: Request) -> str | None:
    # X-Forwarded-For는 브라우저가 보낸 값이 남아 위조할 수 있어 쓰지 않는다
    if get_settings().app_mode == "aws":
        # 접속한 쪽은 CloudFront다. CloudFront가 붙인 "IP:포트"에서 IP만 꺼낸다.
        # 비밀 헤더가 맞는 요청만 여기까지 오므로 이 헤더를 믿는다 (origin_guard, D-340)
        host = request.headers.get("cloudfront-viewer-address", "").rpartition(":")[0]
    else:
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
