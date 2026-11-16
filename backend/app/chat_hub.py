"""채팅 WebSocket 연결 목록. 이 프로세스의 메모리에만 있다 (D-286).

목록은 이벤트 루프에서만 읽고 바꾼다. 스레드풀에서 도는 API는 `from_thread`로 넘긴다.
"""

import anyio.from_thread
from fastapi import WebSocket

MAX_CONNECTIONS = 3  # 계정당 연결 수 (D-290)
CLOSE_NO_SESSION = 4401
CLOSE_BAD_ORIGIN = 4403
CLOSE_TOO_MANY = 4408

# 계정 번호 → [(세션 해시, 연결)]. 오래된 연결이 앞이다
_connections: dict[int, list[tuple[str, WebSocket]]] = {}


async def _close(ws: WebSocket, code: int) -> None:
    try:
        await ws.close(code)
    except Exception:  # noqa: BLE001, S110 - 이미 끊긴 연결이다
        pass


async def add(user_id: int, session_hash: str, ws: WebSocket) -> None:
    conns = _connections.setdefault(user_id, [])
    conns.append((session_hash, ws))
    while len(conns) > MAX_CONNECTIONS:
        _, oldest = conns.pop(0)
        await _close(oldest, CLOSE_TOO_MANY)


def remove(user_id: int, ws: WebSocket) -> None:
    conns = [c for c in _connections.get(user_id, []) if c[1] is not ws]
    if conns:
        _connections[user_id] = conns
    else:
        _connections.pop(user_id, None)


async def _send(user_id: int, payload: dict) -> None:
    for _, ws in list(_connections.get(user_id, [])):
        try:
            await ws.send_json(payload)
        except Exception:  # noqa: BLE001, S110 - 끊긴 연결은 받는 쪽 루프가 목록에서 뺀다
            pass


async def _close_session(session_hash: str) -> None:
    for user_id, conns in list(_connections.items()):
        for h, ws in conns:
            if h == session_hash:
                remove(user_id, ws)
                await _close(ws, CLOSE_NO_SESSION)


def send_from_thread(user_id: int, payload: dict) -> None:
    anyio.from_thread.run(_send, user_id, payload)


def close_session_from_thread(session_hash: str) -> None:
    """로그아웃한 세션으로 연 연결을 닫는다 (D-290)."""
    anyio.from_thread.run(_close_session, session_hash)
