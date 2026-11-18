"""채팅 API 29~34 (05장 5.12, D-284~D-290, D-338)"""

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, WebSocket
from pydantic import AwareDatetime, BaseModel, StringConstraints
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app import chat_hub
from app.auth import COOKIE_NAME, current_user, user_by_sid
from app.config import get_settings
from app.db import get_engine
from app.errors import ApiError
from app.security import token_hash
from app.uploads import _iso

router = APIRouter(prefix="/api/chats")

CHAT_DAYS = 30  # 메시지 보관 기간 (01장 1.6, D-288)
MAX_BODY = 1000
RATE_SECONDS = 10
RATE_COUNT = 10

# 메시지는 두 계정 쌍에 붙는다. 역할로 칼럼을 고르고 SQL에는 상수만 넣는다 (D-285)
_COLS = {
    "admin": ("admin_user_id", "victim_user_id"),
    "victim": ("victim_user_id", "admin_user_id"),
}

Body = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=MAX_BODY, pattern=r"^[^\x00]*$"
    ),
]


class SendBody(BaseModel):
    body: Body


class ReadBody(BaseModel):
    last_read_message_id: int


class NoticesSeenBody(BaseModel):
    seen_at: AwareDatetime


def _message(r, user_id: int) -> dict:
    return {
        "id": r.id,
        "mine": r.sender_user_id == user_id,
        "body": r.body,
        "created_at": _iso(r.created_at),
    }


def _check_peer(conn, user: dict, peer_user_id: int) -> None:
    """수락한 사건이 있는 상대만. 사건 숨김은 보지 않는다. 아니면 404 (D-287)"""
    me_col, peer_col = _COLS[user["role"]]
    found = conn.execute(
        text(
            f"SELECT 1 FROM cases WHERE {me_col} = :u AND {peer_col} = :p "  # noqa: S608 - 상수만
            "AND accepted_at IS NOT NULL LIMIT 1"
        ),
        {"u": user["id"], "p": peer_user_id},
    ).first()
    if not found:
        raise ApiError(404, "CHAT_NOT_FOUND", "chat not found")


@router.get("")
def list_chats(user: Annotated[dict, Depends(current_user)]):
    me_col, peer_col = _COLS[user["role"]]
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT p.id AS peer_user_id, p.name AS peer_name,
                       m.id, m.sender_user_id, m.body, m.created_at,
                       (SELECT count(*) FROM chat_messages x
                         WHERE x.{me_col} = :u AND x.{peer_col} = p.id
                           AND x.sender_user_id = p.id
                           AND x.id > COALESCE(r.last_read_message_id, 0)
                           AND x.created_at > now() - make_interval(days => :d)) AS unread
                  FROM users p
                  LEFT JOIN chat_reads r ON r.user_id = :u AND r.peer_user_id = p.id
                  LEFT JOIN LATERAL (
                       SELECT id, sender_user_id, body, created_at FROM chat_messages
                        WHERE {me_col} = :u AND {peer_col} = p.id
                          AND created_at > now() - make_interval(days => :d)
                        ORDER BY id DESC LIMIT 1) m ON true
                 WHERE p.id IN (SELECT {peer_col} FROM cases
                                 WHERE {me_col} = :u AND accepted_at IS NOT NULL)
                 ORDER BY m.id DESC NULLS LAST, p.id
                """  # noqa: S608 - 상수만
            ),
            {"u": user["id"], "d": CHAT_DAYS},
        ).all()
    items = [
        {
            "peer_user_id": r.peer_user_id,
            "peer_name": r.peer_name,
            "last_message": _message(r, user["id"]) if r.id is not None else None,
            "unread": r.unread,
        }
        for r in rows
    ]
    return {"items": items, "unread_total": sum(i["unread"] for i in items)}


@router.get("/{peer_user_id}/messages")
def list_messages(
    peer_user_id: int,
    user: Annotated[dict, Depends(current_user)],
    before_id: Annotated[int | None, Query()] = None,
    after_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    if before_id is not None and after_id is not None:
        raise ApiError(422, "VALIDATION_FAILED", "before_id and after_id cannot be used together")
    me_col, peer_col = _COLS[user["role"]]
    if after_id is not None:
        cond, order = "AND id > :cursor", "ASC"
    elif before_id is not None:
        cond, order = "AND id < :cursor", "DESC"
    else:
        cond, order = "", "DESC"
    with get_engine().connect() as conn:
        _check_peer(conn, user, peer_user_id)
        rows = conn.execute(
            text(
                f"SELECT id, sender_user_id, body, created_at FROM chat_messages "  # noqa: S608
                f"WHERE {me_col} = :u AND {peer_col} = :p "
                f"AND created_at > now() - make_interval(days => :d) {cond} "
                f"ORDER BY id {order} LIMIT :n"
            ),
            {
                "u": user["id"],
                "p": peer_user_id,
                "d": CHAT_DAYS,
                "cursor": after_id if after_id is not None else before_id,
                "n": limit + 1,  # 하나 더 읽어 더 있는지 본다
            },
        ).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    if order == "DESC":
        rows.reverse()
    return {"items": [_message(r, user["id"]) for r in rows], "has_more": has_more}


@router.post("/{peer_user_id}/messages", status_code=201)
def send_message(peer_user_id: int, body: SendBody, user: Annotated[dict, Depends(current_user)]):
    me_col, peer_col = _COLS[user["role"]]
    with get_engine().begin() as conn:
        _check_peer(conn, user, peer_user_id)
        recent = conn.execute(
            text(
                "SELECT count(*) FROM chat_messages WHERE sender_user_id = :u "
                "AND created_at > now() - make_interval(secs => :s)"
            ),
            {"u": user["id"], "s": RATE_SECONDS},
        ).scalar_one()
        if recent >= RATE_COUNT:
            raise ApiError(429, "CHAT_RATE_LIMITED", "too many messages")
        row = conn.execute(
            text(
                f"INSERT INTO chat_messages ({me_col}, {peer_col}, sender_user_id, body) "  # noqa: S608
                "VALUES (:u, :p, :u, :b) RETURNING id, sender_user_id, body, created_at"
            ),
            {"u": user["id"], "p": peer_user_id, "b": body.body},
        ).one()
    # 저장이 끝난 뒤 열려 있는 연결에 보낸다. 내 다른 탭에도 보낸다 (D-286, D-290)
    for to, peer in ((peer_user_id, user["id"]), (user["id"], peer_user_id)):
        chat_hub.send_from_thread(
            to, {"type": "message", "peer_user_id": peer, "message": _message(row, to)}
        )
    return _message(row, user["id"])


@router.put("/{peer_user_id}/read", status_code=204)
def mark_read(peer_user_id: int, body: ReadBody, user: Annotated[dict, Depends(current_user)]):
    """읽은 위치는 앞으로만 간다. 이 대화의 마지막 메시지보다 크면 그 번호로 낮춘다 (D-289)"""
    me_col, peer_col = _COLS[user["role"]]
    with get_engine().begin() as conn:
        _check_peer(conn, user, peer_user_id)
        conn.execute(
            text(
                f"""
                INSERT INTO chat_reads (user_id, peer_user_id, last_read_message_id)
                SELECT :u, :p, LEAST(:m, max(id)) FROM chat_messages
                 WHERE {me_col} = :u AND {peer_col} = :p
                HAVING count(*) > 0 AND :m > 0
                ON CONFLICT (user_id, peer_user_id) DO UPDATE
                   SET last_read_message_id = EXCLUDED.last_read_message_id, updated_at = now()
                 WHERE chat_reads.last_read_message_id < EXCLUDED.last_read_message_id
                """  # noqa: S608 - 상수만
            ),
            {"u": user["id"], "p": peer_user_id, "m": body.last_read_message_id},
        )


@router.put("/{peer_user_id}/notices-seen", status_code=204)
def mark_notices_seen(
    peer_user_id: int, body: NoticesSeenBody, user: Annotated[dict, Depends(current_user)]
):
    """알림 본 시각은 앞으로만 가고, 지금보다 늦으면 지금으로 낮춘다.
    수락 전 사건의 상대도 된다(피해자가 초대 알림을 본다). 나와 묶인 사건이 없으면 404 (D-338)"""
    me_col, peer_col = _COLS[user["role"]]
    with get_engine().begin() as conn:
        found = conn.execute(
            text(
                f"SELECT 1 FROM cases WHERE {me_col} = :u AND {peer_col} = :p LIMIT 1"  # noqa: S608 - 상수만
            ),
            {"u": user["id"], "p": peer_user_id},
        ).first()
        if not found:
            raise ApiError(404, "CHAT_NOT_FOUND", "chat not found")
        conn.execute(
            text(
                """
                INSERT INTO chat_reads (user_id, peer_user_id, notices_seen_at)
                VALUES (:u, :p, LEAST(CAST(:s AS timestamptz), now()))
                ON CONFLICT (user_id, peer_user_id) DO UPDATE
                   SET notices_seen_at = EXCLUDED.notices_seen_at, updated_at = now()
                 WHERE chat_reads.notices_seen_at IS NULL
                    OR chat_reads.notices_seen_at < EXCLUDED.notices_seen_at
                """
            ),
            {"u": user["id"], "p": peer_user_id, "s": body.seen_at},
        )


def _same_origin(ws: WebSocket) -> bool:
    """`Origin`이 접속한 주소(`Host`)와 같은지. 로컬 모드는 개발 서버의 localhost도 받는다 (D-286)"""
    origin = urlsplit(ws.headers.get("origin", ""))
    if not origin.netloc:
        return False
    if origin.netloc == ws.headers.get("host"):
        return True
    return get_settings().app_mode == "local" and origin.hostname in ("localhost", "127.0.0.1")


@router.websocket("/ws")
async def chat_socket(ws: WebSocket):
    # 닫는 코드를 화면이 읽을 수 있게 먼저 받고 나서 닫는다
    await ws.accept()
    if not _same_origin(ws):
        await ws.close(chat_hub.CLOSE_BAD_ORIGIN)
        return
    sid = ws.cookies.get(COOKIE_NAME)
    user = await run_in_threadpool(user_by_sid, sid)
    if user is None:
        await ws.close(chat_hub.CLOSE_NO_SESSION)
        return
    await chat_hub.add(user["id"], token_hash(sid), ws)
    try:
        # 화면이 보낸 내용은 읽지 않고 버린다. 끊길 때까지 기다리기만 한다
        while (await ws.receive())["type"] != "websocket.disconnect":
            pass
    finally:
        chat_hub.remove(user["id"], ws)
