from datetime import timedelta

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from app import access_log
from app.db import get_engine
from app.errors import ApiError
from app.security import dummy_hash, new_token, token_hash, verify_password

SESSION_DAYS = 7  # 01장 1.6
COOKIE_NAME = "sid"
COOKIE_MAX_AGE = int(timedelta(days=SESSION_DAYS).total_seconds())

router = APIRouter(prefix="/api/auth")


class LoginBody(BaseModel):
    login_id: str = Field(min_length=1)
    password: str = Field(min_length=1)


def current_user(request: Request) -> dict:
    """세션 쿠키로 로그인한 사용자를 찾는다. 없거나 만료면 401."""
    sid = request.cookies.get(COOKIE_NAME)
    if sid:
        with get_engine().connect() as conn:
            row = conn.execute(
                text(
                    "SELECT u.id, u.login_id, u.name FROM sessions s "
                    "JOIN users u ON u.id = s.user_id "
                    "WHERE s.token_hash = :h AND s.expires_at > now()"
                ),
                {"h": token_hash(sid)},
            ).one_or_none()
        if row:
            return {"id": row.id, "login_id": row.login_id, "name": row.name}
    raise ApiError(401, "UNAUTHENTICATED", "login required")


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    with get_engine().connect() as conn:
        user = conn.execute(
            text("SELECT id, login_id, name, password_hash FROM users WHERE login_id = :l"),
            {"l": body.login_id},
        ).one_or_none()
    ok = verify_password(body.password, user.password_hash if user else dummy_hash())
    if not user or not ok:
        raise ApiError(401, "LOGIN_FAILED", "invalid login_id or password")

    token = new_token()
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sessions (token_hash, user_id, expires_at) "
                "VALUES (:h, :u, now() + make_interval(days => :d))"
            ),
            {"h": token_hash(token), "u": user.id, "d": SESSION_DAYS},
        )
    access_log.write_access_log(access_log.LOGIN, request, user_id=user.id)

    # Secure는 HTTPS가 없어 켜지 않는다 (D-31, D-60)
    response.set_cookie(
        COOKIE_NAME, token, max_age=COOKIE_MAX_AGE, path="/", httponly=True, samesite="lax"
    )
    return {"id": user.id, "login_id": user.login_id, "name": user.name}


@router.post("/logout", status_code=204)
def logout(request: Request):
    sid = request.cookies.get(COOKIE_NAME)
    if sid:
        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM sessions WHERE token_hash = :h"), {"h": token_hash(sid)})
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")
    return response


@router.get("/me")
def me(request: Request):
    return current_user(request)
