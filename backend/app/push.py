"""웹 푸시: 39·40번 API와, 주기 작업이 부르는 보내기 (D-348)."""

import base64
import binascii
import json
import logging
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from pywebpush import WebPushException, webpush
from sqlalchemy import text

from app.auth import COOKIE_NAME
from app.config import get_settings
from app.db import get_engine
from app.errors import ApiError
from app.security import token_hash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/push")

TTL_SECONDS = 86400  # 푸시 서버가 알림을 보관하는 시간: 하루 (D-348 7번)
RECENT_MINUTES = 10  # 이보다 오래된 일은 보내지 않는다 (D-348 3번)

# 서버가 이 주소로 요청을 보내므로 알려진 푸시 서버만 받는다. 포함 여부가 아니라 똑같은지 본다 (SSRF, 08장)
PUSH_HOSTS = {"fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com"}
PUSH_HOST_SUFFIX = ".notify.windows.com"

# 05장 5.13 "푸시 내용". 사건 이름·파일 이름은 넣지 않는다
MESSAGES = {
    ("done", "admin"): ("분석이 끝났습니다", "결과를 확인해 주세요."),
    ("done", "victim"): ("분석이 끝났습니다", "관리자와 함께 결과를 확인할 수 있습니다."),
    ("failed", "admin"): ("영상을 분석하지 못했습니다", "영상 상태 화면에서 다시 시도해 주세요."),
    ("failed", "victim"): ("영상을 분석하지 못했습니다", "관리자가 다시 시도할 수 있습니다."),
    ("upload_unconfirmed", "admin"): (
        "업로드가 확인되지 않습니다",
        "같은 사건에 다시 올려 주세요.",
    ),
}


def _enabled() -> bool:
    s = get_settings()
    return bool(s.vapid_private_key and s.vapid_public_key and s.vapid_subject)


def allowed_endpoint(endpoint: str) -> bool:
    try:
        url = urlsplit(endpoint)
        port = url.port
    except ValueError:
        return False
    host = url.hostname or ""
    if url.scheme != "https" or port is not None or url.username or url.password:
        return False
    return host in PUSH_HOSTS or (host.endswith(PUSH_HOST_SUFFIX) and host != PUSH_HOST_SUFFIX[1:])


def _key_length(value: str) -> int:
    try:
        return len(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    except (binascii.Error, ValueError):
        return -1


class Keys(BaseModel):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class SubscriptionBody(BaseModel):
    endpoint: str = Field(max_length=2048)
    keys: Keys


@router.get("/public-key")
def public_key():
    return {"public_key": get_settings().vapid_public_key if _enabled() else None}


@router.put("/subscription", status_code=204)
def save_subscription(body: SubscriptionBody, request: Request):
    sid = request.cookies.get(COOKIE_NAME)
    with get_engine().connect() as conn:
        session_id = (
            conn.execute(
                text("SELECT id FROM sessions WHERE token_hash = :h AND expires_at > now()"),
                {"h": token_hash(sid)},
            ).scalar_one_or_none()
            if sid
            else None
        )
    if session_id is None:
        raise ApiError(401, "UNAUTHENTICATED", "login required")
    if not allowed_endpoint(body.endpoint):
        raise ApiError(422, "VALIDATION_FAILED", "invalid value: endpoint")
    if _key_length(body.keys.p256dh) != 65 or _key_length(body.keys.auth) != 16:
        raise ApiError(422, "VALIDATION_FAILED", "invalid value: keys")
    # 같은 브라우저가 다시 로그인해 구독하면 endpoint가 같으므로 새 세션으로 옮긴다 (D-348 4번)
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO push_subscriptions (session_id, endpoint, p256dh, auth) "
                "VALUES (:s, :e, :p, :a) ON CONFLICT (endpoint) DO UPDATE "
                "SET session_id = EXCLUDED.session_id, p256dh = EXCLUDED.p256dh, auth = EXCLUDED.auth"
            ),
            {"s": session_id, "e": body.endpoint, "p": body.keys.p256dh, "a": body.keys.auth},
        )


# 최근 10분 안에 생긴 일. 업로드 확인 안 됨은 05장 5.5의 upload_failed와 같은 기준이다 (D-47)
_EVENTS = """
SELECT video_id, 'done' AS kind, stage2_ended_at AS event_at FROM analysis_jobs
 WHERE stage2_ended_at > now() - make_interval(mins => :m)
UNION ALL
SELECT video_id, 'failed', status_changed_at FROM analysis_jobs
 WHERE status = 'failed' AND status_changed_at > now() - make_interval(mins => :m)
UNION ALL
SELECT v.id, 'upload_unconfirmed', v.created_at + interval '30 minutes' FROM videos v
 WHERE NOT EXISTS (SELECT 1 FROM analysis_jobs j WHERE j.video_id = v.id)
   AND v.created_at + interval '30 minutes' <= now()
   AND v.created_at + interval '30 minutes' > now() - make_interval(mins => :m)
"""

# 그 영상 사건의 관리자와, 수락한 피해자. 사건을 삭제한 계정과 만료된 세션은 뺀다 (D-233, D-239)
_RECIPIENTS = """
SELECT ps.id, ps.endpoint, ps.p256dh, ps.auth,
       CASE WHEN s.user_id = c.admin_user_id THEN 'admin' ELSE 'victim' END AS role
  FROM videos v
  JOIN cases c ON c.id = v.case_id
  JOIN sessions s ON s.expires_at > now()
   AND ((s.user_id = c.admin_user_id AND c.admin_deleted_at IS NULL)
        OR (:to_victim AND s.user_id = c.victim_user_id
            AND c.accepted_at IS NOT NULL AND c.victim_deleted_at IS NULL))
  JOIN push_subscriptions ps ON ps.session_id = s.id
 WHERE v.id = :v
"""


def send_pending() -> None:
    """주기 작업이 15초마다 부른다. 기록을 먼저 남기고 보내며, 실패해도 다시 보내지 않는다."""
    if not _enabled():
        return
    with get_engine().connect() as conn:
        events = conn.execute(text(_EVENTS), {"m": RECENT_MINUTES}).all()
    for ev in events:
        with get_engine().begin() as conn:
            new = conn.execute(
                text(
                    "INSERT INTO push_events (video_id, kind, event_at) VALUES (:v, :k, :t) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"v": ev.video_id, "k": ev.kind, "t": ev.event_at},
            ).rowcount
        if not new:
            continue
        with get_engine().connect() as conn:
            subs = conn.execute(
                text(_RECIPIENTS), {"v": ev.video_id, "to_victim": ev.kind != "upload_unconfirmed"}
            ).all()
        for sub in subs:
            title, body = MESSAGES[(ev.kind, sub.role)]
            _send(sub, {"title": title, "body": body, "url": f"/#/videos/{ev.video_id}"})


def _send(sub, payload: dict) -> None:
    settings = get_settings()
    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={
                "sub": settings.vapid_subject
            },  # webpush가 aud·exp를 채우므로 매번 새로 만든다
            ttl=TTL_SECONDS,
            timeout=10,
        )
    except WebPushException as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (404, 410):  # 사용자가 알림을 껐거나 구독이 사라짐 (D-348 4번)
            with get_engine().begin() as conn:
                conn.execute(text("DELETE FROM push_subscriptions WHERE id = :i"), {"i": sub.id})
            return
        # endpoint는 브라우저를 특정하는 값이라 로그에 남기지 않는다 (08장)
        logger.warning("push send failed: status %s (subscription %d)", status, sub.id)
    except Exception as exc:  # noqa: BLE001 - 다른 구독은 계속 보낸다
        logger.warning("push send failed: %s (subscription %d)", type(exc).__name__, sub.id)
