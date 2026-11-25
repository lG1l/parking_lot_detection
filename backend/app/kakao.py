"""카카오 인증을 거치는 가입: 35·36번 API (D-346)."""

import logging
import re
import secrets
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text

from app import access_log, rate_limit
from app.auth import start_session
from app.config import get_settings
from app.db import get_engine
from app.errors import ApiError
from app.security import hash_password, new_token, token_hash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth")

AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
USER_URL = "https://kapi.kakao.com/v2/user/me"
KAKAO_TIMEOUT = 10

STATE_COOKIE = "oauth_state"
STATE_COOKIE_PATH = "/api/auth/kakao"  # 콜백(36번)에만 붙는다
PENDING_MINUTES = 10

# 가입 시작(35번)과 비밀번호 재설정 시작(38번)을 합쳐 같은 IP로 1시간에 20회 (D-346 6번)
START_LIMIT = 20
START_WINDOW = 3600

# 콜백이 보내는 프론트 화면 (해시 라우팅)
SIGNUP_PAGE = "/#/signup"
LOGIN_PAGE = "/#/login"

_KINDS = (r"[A-Z]", r"[a-z]", r"[0-9]", r"[^A-Za-z0-9]")


def valid_password(password: str, login_id: str) -> bool:
    """D-346 5번: 2종류 이상이면 10자 이상, 3종류 이상이면 8자 이상. 출력 가능한 ASCII 64자까지."""
    if not re.fullmatch(r"[\x20-\x7e]{8,64}", password) or password == login_id:
        return False
    kinds = sum(bool(re.search(k, password)) for k in _KINDS)
    return kinds >= 3 or (kinds == 2 and len(password) >= 10)


class SignupBody(BaseModel):
    login_id: str = Field(pattern=r"^[a-z0-9]{4,20}$")
    password: str = Field(max_length=64)
    name: str = Field(min_length=1, max_length=20, pattern=r"^[^\x00-\x1f\x7f]+$")
    role: str = Field(pattern=r"^(admin|victim)$")

    @model_validator(mode="after")
    def _check(self):
        if not self.name.strip():
            raise ValueError("name")
        if not valid_password(self.password, self.login_id):
            raise ValueError("password")
        return self


def _configured() -> bool:
    s = get_settings()
    return bool(s.kakao_rest_api_key and s.kakao_client_secret and s.kakao_redirect_uri)


def take_start_attempt(request: Request) -> None:
    ip = access_log.client_ip(request) or "unknown"
    wait = rate_limit.take(("kakao_start", ip), START_LIMIT, START_WINDOW)
    if wait:
        raise ApiError(429, "TOO_MANY_ATTEMPTS", "too many attempts", {"Retry-After": str(wait)})


@router.post("/signup/start")
def signup_start(body: SignupBody, request: Request, response: Response):
    take_start_attempt(request)
    if not _configured():
        raise ApiError(503, "KAKAO_NOT_CONFIGURED", "kakao login is not configured")
    with get_engine().connect() as conn:
        taken = conn.execute(
            text("SELECT 1 FROM users WHERE login_id = :l"), {"l": body.login_id}
        ).first()
    if taken:
        raise ApiError(409, "LOGIN_ID_TAKEN", "login_id is already taken")

    state = new_token()
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO kakao_pending "
                "(state_hash, purpose, login_id, password_hash, name, role, expires_at) "
                "VALUES (:s, 'signup', :l, :p, :n, :r, now() + make_interval(mins => :m))"
            ),
            {
                "s": token_hash(state),
                "l": body.login_id,
                "p": hash_password(body.password),
                "n": body.name,
                "r": body.role,
                "m": PENDING_MINUTES,
            },
        )
    # Secure는 sid와 같은 규칙이다. HTTPS가 없어 아직 켜지 않는다 (D-340)
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=PENDING_MINUTES * 60,
        path=STATE_COOKIE_PATH,
        httponly=True,
        samesite="lax",
    )
    return {"authorize_url": authorize_url(state)}


def authorize_url(state: str) -> str:
    s = get_settings()
    query = {
        "client_id": s.kakao_rest_api_key,
        "redirect_uri": s.kakao_redirect_uri,
        "response_type": "code",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(query)}"


def kakao_user_id(code: str) -> int | None:
    """code를 토큰으로 바꾸고 회원번호를 받는다. 브라우저가 보낸 토큰·회원번호는 믿지 않는다."""
    s = get_settings()
    try:
        token = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": s.kakao_rest_api_key,
                "client_secret": s.kakao_client_secret,
                "redirect_uri": s.kakao_redirect_uri,
                "code": code,
            },
            timeout=KAKAO_TIMEOUT,
        )
        if token.status_code != 200:
            # 응답 본문에 code·토큰이 들어 있을 수 있어 상태 코드만 남긴다 (D-78)
            logger.warning("kakao token exchange failed: status %s", token.status_code)
            return None
        me = requests.get(
            USER_URL,
            headers={"Authorization": f"Bearer {token.json()['access_token']}"},
            timeout=KAKAO_TIMEOUT,
        )
        if me.status_code != 200:
            logger.warning("kakao user lookup failed: status %s", me.status_code)
            return None
        kakao_id = me.json()["id"]
        return kakao_id if isinstance(kakao_id, int) and kakao_id > 0 else None
    except Exception as exc:  # noqa: BLE001 - 어떤 실패든 KAKAO_FAILED로 돌려보낸다
        logger.warning("kakao request failed: %s", type(exc).__name__)
        return None


def _redirect(url: str) -> RedirectResponse:
    response = RedirectResponse(url, status_code=302)
    response.delete_cookie(STATE_COOKIE, path=STATE_COOKIE_PATH, httponly=True, samesite="lax")
    return response


def _fail(page: str, code: str) -> RedirectResponse:
    return _redirect(f"{page}?{urlencode({'error': code})}")


@router.get("/kakao/callback")
def kakao_callback(
    request: Request, state: str = "", code: str = "", error: str = ""
) -> RedirectResponse:
    cookie = request.cookies.get(STATE_COOKIE, "")
    if not state or not cookie or not secrets.compare_digest(state, cookie):
        return _fail(LOGIN_PAGE, "KAKAO_EXPIRED")
    # 맞으면 먼저 지운다. 뒤에서 실패해도 같은 state로 다시 시도할 수 없다
    with get_engine().begin() as conn:
        pending = conn.execute(
            text(
                "DELETE FROM kakao_pending WHERE state_hash = :s "
                "RETURNING purpose, login_id, password_hash, name, role, expires_at > now() AS live"
            ),
            {"s": token_hash(state)},
        ).one_or_none()
    if pending is None or pending.purpose != "signup":
        return _fail(LOGIN_PAGE, "KAKAO_EXPIRED")
    if not pending.live:
        return _fail(SIGNUP_PAGE, "KAKAO_EXPIRED")
    if error:
        return _fail(SIGNUP_PAGE, "KAKAO_CANCELLED")
    kakao_id = kakao_user_id(code) if code else None
    if kakao_id is None:
        return _fail(SIGNUP_PAGE, "KAKAO_FAILED")

    with get_engine().begin() as conn:
        user_id = conn.execute(
            text(
                "INSERT INTO users (login_id, password_hash, name, role, kakao_id) "
                "VALUES (:l, :p, :n, :r, :k) ON CONFLICT DO NOTHING RETURNING id"
            ),
            {
                "l": pending.login_id,
                "p": pending.password_hash,
                "n": pending.name,
                "r": pending.role,
                "k": kakao_id,
            },
        ).scalar_one_or_none()
        if user_id is None:
            used = conn.execute(
                text("SELECT 1 FROM users WHERE kakao_id = :k"), {"k": kakao_id}
            ).first()
    if user_id is None:
        return _fail(SIGNUP_PAGE, "KAKAO_ALREADY_USED" if used else "LOGIN_ID_TAKEN")

    response = _redirect("/")
    start_session(request, response, user_id)
    return response
