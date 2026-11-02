"""사건 API 24·21·22 (05장 5.4, D-204·D-206)"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from app import access_log
from app.auth import current_admin, current_user
from app.db import get_engine
from app.errors import ApiError
from app.uploads import _iso

router = APIRouter(prefix="/api")


class CaseBody(BaseModel):
    victim_login_id: str = Field(min_length=1, pattern=r"^[^\x00]*$")


def mask_name(name: str) -> str:
    """첫 글자와 끝 글자만 남긴다. 두 글자는 끝 글자를 가린다 (D-206)"""
    if len(name) < 2:
        return "*"
    if len(name) == 2:
        return name[0] + "*"
    return name[0] + "*" * (len(name) - 2) + name[-1]


def _victim(conn, login_id: str):
    # 없는 아이디와 관리자 계정을 같은 코드로 돌려줘 계정 종류가 드러나지 않게 한다 (D-206)
    row = conn.execute(
        text("SELECT id, login_id, name FROM users WHERE login_id = :l AND role = 'victim'"),
        {"l": login_id},
    ).one_or_none()
    if not row:
        raise ApiError(422, "INVITEE_INVALID", "no victim account with this login_id")
    return row


@router.get("/users/lookup")
def lookup_invitee(
    request: Request,
    user: Annotated[dict, Depends(current_admin)],
    login_id: Annotated[str, Query(min_length=1, pattern=r"^[^\x00]*$")],
):
    with get_engine().connect() as conn:
        victim = _victim(conn, login_id)
    access_log.write_access_log(access_log.LOOKUP_INVITEE, request, user_id=user["id"])
    return {"login_id": victim.login_id, "masked_name": mask_name(victim.name)}


@router.post("/cases", status_code=201)
def create_case(body: CaseBody, request: Request, user: Annotated[dict, Depends(current_admin)]):
    with get_engine().begin() as conn:
        victim = _victim(conn, body.victim_login_id)
        row = conn.execute(
            text(
                "INSERT INTO cases (admin_user_id, victim_user_id) VALUES (:a, :v) "
                "RETURNING id, created_at"
            ),
            {"a": user["id"], "v": victim.id},
        ).one()
    access_log.write_access_log(access_log.CREATE_CASE, request, user_id=user["id"])
    return {"id": row.id, "victim_name": victim.name, "created_at": _iso(row.created_at)}


@router.get("/cases")
def list_cases(user: Annotated[dict, Depends(current_user)]):
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.id, a.name AS admin_name, v.name AS victim_name, c.created_at "
                "FROM cases c JOIN users a ON a.id = c.admin_user_id "
                "JOIN users v ON v.id = c.victim_user_id "
                "WHERE c.admin_user_id = :u OR c.victim_user_id = :u "
                "ORDER BY c.created_at DESC, c.id DESC"
            ),
            {"u": user["id"]},
        ).all()
    return {
        "items": [
            {
                "id": r.id,
                "admin_name": r.admin_name,
                "victim_name": r.victim_name,
                "created_at": _iso(r.created_at),
            }
            for r in rows
        ]
    }
