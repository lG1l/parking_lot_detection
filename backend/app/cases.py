"""사건 API 24·21·22·26·27·28 (05장 5.4, D-204·D-206·D-233·D-239·D-240)"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import text

from app import access_log
from app.auth import current_admin, current_user, current_victim
from app.db import get_engine
from app.errors import ApiError
from app.uploads import _iso

router = APIRouter(prefix="/api")


# 앞뒤 공백을 지운 뒤 1~50자 (D-237, D-240)
CaseName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50, pattern=r"^[^\x00]*$"),
]


class CaseBody(BaseModel):
    victim_login_id: str = Field(min_length=1, pattern=r"^[^\x00]*$")
    case_name: CaseName


class RenameBody(BaseModel):
    case_name: CaseName


# 이름·삭제 칸은 계정마다 따로 둔다. 역할로 칼럼을 고르고 SQL에는 상수만 넣는다 (D-239, D-240)
_COLS = {
    "admin": ("admin_user_id", "admin_case_name", "admin_deleted_at"),
    "victim": ("victim_user_id", "victim_case_name", "victim_deleted_at"),
}

_ITEM = """
SELECT c.id, a.name AS admin_name, v.name AS victim_name, c.created_at, c.accepted_at,
       c.{name_col} AS case_name
  FROM cases c JOIN users a ON a.id = c.admin_user_id
  JOIN users v ON v.id = c.victim_user_id
 WHERE c.{user_col} = :u AND c.{deleted_col} IS NULL
"""


def _item(r) -> dict:
    return {
        "id": r.id,
        "admin_name": r.admin_name,
        "victim_name": r.victim_name,
        "case_name": r.case_name,
        "created_at": _iso(r.created_at),
        "accepted_at": _iso(r.accepted_at) if r.accepted_at else None,
    }


def _item_sql(role: str, where: str = "") -> str:
    user_col, name_col, deleted_col = _COLS[role]
    return _ITEM.format(user_col=user_col, name_col=name_col, deleted_col=deleted_col) + where


def _my_case(conn, case_id: int, user: dict) -> None:
    """27·28번: 내가 숨기지 않은 내 사건. 피해자는 수락한 사건만. 아니면 404 (D-239)"""
    user_col, _, deleted_col = _COLS[user["role"]]
    accepted = " AND accepted_at IS NOT NULL" if user["role"] == "victim" else ""
    found = conn.execute(
        text(
            f"SELECT 1 FROM cases WHERE id = :c AND {user_col} = :u "  # noqa: S608 - 상수만
            f"AND {deleted_col} IS NULL{accepted} FOR UPDATE"
        ),
        {"c": case_id, "u": user["id"]},
    ).first()
    if not found:
        raise ApiError(404, "CASE_NOT_FOUND", "case not found")


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
                # 피해자 쪽 이름은 연결한 날(한국 시간)로 시작한다 (D-240)
                "INSERT INTO cases (admin_user_id, victim_user_id, admin_case_name, victim_case_name) "
                "VALUES (:a, :v, :n, to_char(now() AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD') || ' 연결') "
                "RETURNING id, created_at"
            ),
            {"a": user["id"], "v": victim.id, "n": body.case_name},
        ).one()
    access_log.write_access_log(access_log.CREATE_CASE, request, user_id=user["id"])
    return {"id": row.id, "victim_name": victim.name, "created_at": _iso(row.created_at)}


@router.get("/cases")
def list_cases(user: Annotated[dict, Depends(current_user)]):
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(_item_sql(user["role"], " ORDER BY c.created_at DESC, c.id DESC")),
            {"u": user["id"]},
        ).all()
    return {"items": [_item(r) for r in rows]}


@router.post("/cases/{case_id}/accept", status_code=204)
def accept_case(case_id: int, request: Request, user: Annotated[dict, Depends(current_victim)]):
    """이미 수락했으면 아무것도 바꾸지 않고 204 (D-233)"""
    with get_engine().begin() as conn:
        row = conn.execute(
            text("SELECT accepted_at FROM cases WHERE id = :c AND victim_user_id = :u FOR UPDATE"),
            {"c": case_id, "u": user["id"]},
        ).one_or_none()
        if row is None:
            raise ApiError(404, "CASE_NOT_FOUND", "case not found")
        if row.accepted_at is not None:
            return
        conn.execute(text("UPDATE cases SET accepted_at = now() WHERE id = :c"), {"c": case_id})
    access_log.write_access_log(access_log.ACCEPT_CASE, request, user_id=user["id"])


@router.patch("/cases/{case_id}")
def rename_case(case_id: int, body: RenameBody, user: Annotated[dict, Depends(current_user)]):
    """내 쪽 이름만 바꾼다. 상대 계정의 이름은 그대로다 (D-240)"""
    _, name_col, _ = _COLS[user["role"]]
    with get_engine().begin() as conn:
        _my_case(conn, case_id, user)
        conn.execute(
            text(f"UPDATE cases SET {name_col} = :n WHERE id = :c"),  # noqa: S608 - 상수만
            {"n": body.case_name, "c": case_id},
        )
        row = conn.execute(
            text(_item_sql(user["role"], " AND c.id = :c")), {"u": user["id"], "c": case_id}
        ).one()
    return _item(row)


@router.delete("/cases/{case_id}", status_code=204)
def delete_case(case_id: int, user: Annotated[dict, Depends(current_user)]):
    """내 쪽에서만 숨긴다. 영상·분석 결과·S3 파일은 30일 파기 일정을 그대로 따른다 (D-239)"""
    _, _, deleted_col = _COLS[user["role"]]
    with get_engine().begin() as conn:
        _my_case(conn, case_id, user)
        conn.execute(
            text(f"UPDATE cases SET {deleted_col} = now() WHERE id = :c"),  # noqa: S608 - 상수만
            {"c": case_id},
        )
