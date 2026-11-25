from datetime import timedelta

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from app import access_log, chat_hub, rate_limit
from app.db import get_engine
from app.errors import ApiError
from app.security import dummy_hash, new_token, token_hash, verify_password

SESSION_DAYS = 7  # 01장 1.6
COOKIE_NAME = "sid"
COOKIE_MAX_AGE = int(timedelta(days=SESSION_DAYS).total_seconds())
# 로그인 실패 제한 (D-346 6번): 같은 IP·아이디 15분 5회, 같은 IP 15분 30회
LOGIN_WINDOW = 15 * 60
LOGIN_LIMIT_PER_ID = 5
LOGIN_LIMIT_PER_IP = 30

router = APIRouter(prefix="/api/auth")


class LoginBody(BaseModel):
    login_id: str = Field(min_length=1, pattern=r"^[^\x00]*$")
    password: str = Field(min_length=1)


def user_by_sid(sid: str | None) -> dict | None:
    """세션 쿠키 값으로 로그인한 사용자를 찾는다. 없거나 만료면 None."""
    if sid:
        with get_engine().connect() as conn:
            row = conn.execute(
                text(
                    "SELECT u.id, u.login_id, u.name, u.role FROM sessions s "
                    "JOIN users u ON u.id = s.user_id "
                    "WHERE s.token_hash = :h AND s.expires_at > now()"
                ),
                {"h": token_hash(sid)},
            ).one_or_none()
        if row:
            return {"id": row.id, "login_id": row.login_id, "name": row.name, "role": row.role}
    return None


def current_user(request: Request) -> dict:
    """세션 쿠키로 로그인한 사용자를 찾는다. 없거나 만료면 401."""
    user = user_by_sid(request.cookies.get(COOKIE_NAME))
    if user is None:
        raise ApiError(401, "UNAUTHENTICATED", "login required")
    return user


def current_admin(request: Request) -> dict:
    """관리자 계정만 통과시킨다. 피해자 계정이면 403 (D-204)."""
    user = current_user(request)
    if user["role"] != "admin":
        raise ApiError(403, "ROLE_NOT_ALLOWED", "admin account required")
    return user


def current_victim(request: Request) -> dict:
    """피해자 계정만 통과시킨다. 관리자 계정이면 403 (D-233)."""
    user = current_user(request)
    if user["role"] != "victim":
        raise ApiError(403, "ROLE_NOT_ALLOWED", "victim account required")
    return user


def start_session(request: Request, response: Response, user_id: int) -> None:
    """세션 행을 만들고 sid 쿠키를 내린다. 로그인과 카카오 가입(36번)이 같이 쓴다."""
    token = new_token()
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sessions (token_hash, user_id, expires_at) "
                "VALUES (:h, :u, now() + make_interval(days => :d))"
            ),
            {"h": token_hash(token), "u": user_id, "d": SESSION_DAYS},
        )
    access_log.write_access_log(access_log.LOGIN, request, user_id=user_id)

    # Secure는 HTTPS가 없어 켜지 않는다 (D-31, D-60)
    response.set_cookie(
        COOKIE_NAME, token, max_age=COOKIE_MAX_AGE, path="/", httponly=True, samesite="lax"
    )


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    ip = access_log.client_ip(request) or "unknown"
    per_id, per_ip = ("login", ip, body.login_id), ("login", ip)
    wait = rate_limit.blocked_for(per_id, per_ip)
    if wait:
        raise ApiError(
            429, "TOO_MANY_ATTEMPTS", "too many failed logins", {"Retry-After": str(wait)}
        )

    with get_engine().connect() as conn:
        user = conn.execute(
            text("SELECT id, login_id, name, role, password_hash FROM users WHERE login_id = :l"),
            {"l": body.login_id},
        ).one_or_none()
    ok = verify_password(body.password, user.password_hash if user else dummy_hash())
    if not user or not ok:
        rate_limit.record_failure(per_id, LOGIN_LIMIT_PER_ID, LOGIN_WINDOW)
        rate_limit.record_failure(per_ip, LOGIN_LIMIT_PER_IP, LOGIN_WINDOW)
        raise ApiError(401, "LOGIN_FAILED", "invalid login_id or password")

    rate_limit.clear(per_id)
    start_session(request, response, user.id)
    return {"id": user.id, "login_id": user.login_id, "name": user.name, "role": user.role}


@router.post("/logout", status_code=204)
def logout(request: Request):
    sid = request.cookies.get(COOKIE_NAME)
    if sid:
        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM sessions WHERE token_hash = :h"), {"h": token_hash(sid)})
        # 열린 탭에 메시지가 더 가지 않게 그 세션의 채팅 연결을 닫는다 (D-290)
        chat_hub.close_session_from_thread(token_hash(sid))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")
    return response


@router.get("/me")
def me(request: Request):
    return current_user(request)
