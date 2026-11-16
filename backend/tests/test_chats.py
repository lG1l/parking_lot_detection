import pytest
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect

from app import chat_hub, periodic
from app.db import get_engine
from tests.conftest import make_client
from tests.test_auth import make_user

ORIGIN = {"origin": "http://testserver"}


def sql(query, **params):
    with get_engine().begin() as conn:
        return conn.execute(text(query), params)


def login(c, login_id):
    assert c.post("/api/auth/login", json={"login_id": login_id, "password": "demo-password"})


def client_of(login_id):
    c = make_client()
    login(c, login_id)
    return c


def link(admin_id, victim_id, accepted=True):
    sql(
        "INSERT INTO cases (admin_user_id, victim_user_id, accepted_at) "
        "VALUES (:a, :v, CASE WHEN :ok THEN now() END)",
        a=admin_id,
        v=victim_id,
        ok=accepted,
    )


def code(r):
    return r.status_code, r.json()["error"]["code"]


@pytest.fixture
def pair():
    """수락한 사건으로 묶인 관리자·피해자. (관리자 화면, 피해자 화면, 관리자 번호, 피해자 번호)"""
    a = make_user(login_id="admin1", name="관리자", role="admin")
    v = make_user(login_id="victim1", name="홍길동", role="victim")
    link(a, v)
    return client_of("admin1"), client_of("victim1"), a, v


# ---- 29~32번 ----


def test_send_list_and_unread(pair):
    admin, victim, a, v = pair
    assert admin.get("/api/chats").json() == {
        "items": [{"peer_user_id": v, "peer_name": "홍길동", "last_message": None, "unread": 0}],
        "unread_total": 0,
    }
    sent = admin.post(f"/api/chats/{v}/messages", json={"body": "  안녕하세요  "})
    assert sent.status_code == 201
    assert (sent.json()["mine"], sent.json()["body"]) == (True, "안녕하세요")
    admin.post(f"/api/chats/{v}/messages", json={"body": "영상 올렸습니다"})

    chats = victim.get("/api/chats").json()
    assert chats["unread_total"] == 1 + 1
    item = chats["items"][0]
    assert (item["peer_user_id"], item["peer_name"], item["unread"]) == (a, "관리자", 2)
    assert (item["last_message"]["body"], item["last_message"]["mine"]) == (
        "영상 올렸습니다",
        False,
    )
    # 내가 보낸 메시지는 안 읽은 수에 넣지 않는다
    assert admin.get("/api/chats").json()["unread_total"] == 0

    got = victim.get(f"/api/chats/{a}/messages").json()
    assert [m["body"] for m in got["items"]] == ["안녕하세요", "영상 올렸습니다"]
    assert got["has_more"] is False


def test_messages_paging(pair):
    _, victim, a, v = pair
    for i in range(5):
        sql(
            "INSERT INTO chat_messages (admin_user_id, victim_user_id, sender_user_id, body) "
            "VALUES (:a, :v, :a, :b)",
            a=a,
            v=v,
            b=f"m{i + 1}",
        )

    def bodies(**params):
        r = victim.get(f"/api/chats/{a}/messages", params=params).json()
        return [m["body"] for m in r["items"]], r["has_more"]

    assert bodies(limit=2) == (["m4", "m5"], True)
    assert bodies(limit=2, before_id=4) == (["m2", "m3"], True)
    assert bodies(limit=2, before_id=2) == (["m1"], False)
    assert bodies(limit=2, after_id=1) == (["m2", "m3"], True)
    assert bodies(after_id=3) == (["m4", "m5"], False)
    r = victim.get(f"/api/chats/{a}/messages", params={"before_id": 3, "after_id": 1})
    assert code(r) == (422, "VALIDATION_FAILED")
    r = victim.get(f"/api/chats/{a}/messages", params={"limit": 101})
    assert code(r) == (422, "VALIDATION_FAILED")


def test_read_moves_forward_only(pair):
    admin, victim, a, v = pair
    for body in ["하나", "둘", "셋"]:
        admin.post(f"/api/chats/{v}/messages", json={"body": body})

    def unread():
        return victim.get("/api/chats").json()["unread_total"]

    def read(message_id):
        r = victim.put(f"/api/chats/{a}/read", json={"last_read_message_id": message_id})
        assert r.status_code == 204

    read(2)
    assert unread() == 1
    read(1)  # 뒤로 가지 않는다
    assert unread() == 1
    read(999)  # 마지막 메시지 번호로 낮춘다
    assert unread() == 0
    admin.post(f"/api/chats/{v}/messages", json={"body": "넷"})
    assert unread() == 1
    # 상대의 읽은 위치는 바뀌지 않는다
    assert sql("SELECT count(*) FROM chat_reads").scalar_one() == 1


def test_read_without_messages_stores_nothing(pair):
    _, victim, a, _ = pair
    r = victim.put(f"/api/chats/{a}/read", json={"last_read_message_id": 5})
    assert r.status_code == 204
    assert sql("SELECT count(*) FROM chat_reads").scalar_one() == 0


def test_only_accounts_with_accepted_case(pair):
    admin, _, a, v = pair
    other_v = make_user(login_id="victim2", name="박피해", role="victim")
    link(a, other_v, accepted=False)  # 수락 전
    other_a = make_user(login_id="admin2", name="다른관리자", role="admin")
    for peer in [other_v, other_a, a, 9999]:  # 수락 전, 사건 없음, 나 자신, 없는 계정
        assert code(admin.get(f"/api/chats/{peer}/messages")) == (404, "CHAT_NOT_FOUND")
        r = admin.post(f"/api/chats/{peer}/messages", json={"body": "x"})
        assert code(r) == (404, "CHAT_NOT_FOUND")
        r = admin.put(f"/api/chats/{peer}/read", json={"last_read_message_id": 1})
        assert code(r) == (404, "CHAT_NOT_FOUND")
    assert [i["peer_user_id"] for i in admin.get("/api/chats").json()["items"]] == [v]
    assert sql("SELECT count(*) FROM chat_messages").scalar_one() == 0


def test_other_pair_cannot_read(pair):
    admin, _, _, v = pair
    admin.post(f"/api/chats/{v}/messages", json={"body": "비밀"})
    other_a = make_user(login_id="admin2", name="다른관리자", role="admin")
    link(other_a, v)
    other = client_of("admin2")
    assert other.get(f"/api/chats/{v}/messages").json()["items"] == []
    assert other.get("/api/chats").json()["items"][0]["last_message"] is None


def test_hidden_case_still_chats(pair):
    admin, _, _, v = pair
    sql("UPDATE cases SET admin_deleted_at = now(), victim_deleted_at = now()")
    assert admin.post(f"/api/chats/{v}/messages", json={"body": "x"}).status_code == 201


def test_body_validation(pair):
    admin, _, _, v = pair
    for body in ["", "   ", "가" * 1001, "a\u0000b", None]:
        r = admin.post(f"/api/chats/{v}/messages", json={"body": body})
        assert code(r) == (422, "VALIDATION_FAILED")
    assert admin.post(f"/api/chats/{v}/messages", json={"body": "가" * 1000}).status_code == 201


def test_rate_limit(pair):
    admin, _, _, v = pair
    for _ in range(10):
        assert admin.post(f"/api/chats/{v}/messages", json={"body": "x"}).status_code == 201
    assert code(admin.post(f"/api/chats/{v}/messages", json={"body": "x"})) == (
        429,
        "CHAT_RATE_LIMITED",
    )
    sql("UPDATE chat_messages SET created_at = now() - interval '11 seconds'")
    assert admin.post(f"/api/chats/{v}/messages", json={"body": "x"}).status_code == 201


def test_requires_login():
    c = make_client()
    assert code(c.get("/api/chats")) == (401, "UNAUTHENTICATED")
    assert code(c.post("/api/chats/1/messages", json={"body": "x"})) == (401, "UNAUTHENTICATED")


def test_old_messages_hidden_and_deleted(pair):
    admin, victim, a, v = pair
    admin.post(f"/api/chats/{v}/messages", json={"body": "옛날"})
    admin.post(f"/api/chats/{v}/messages", json={"body": "최근"})
    sql("UPDATE chat_messages SET created_at = now() - interval '31 days' WHERE body = '옛날'")
    # 주기 작업이 지우기 전에도 주지 않는다 (D-288)
    assert [m["body"] for m in victim.get(f"/api/chats/{a}/messages").json()["items"]] == ["최근"]
    assert victim.get("/api/chats").json()["unread_total"] == 1
    periodic.delete_old_chat_messages()
    assert sql("SELECT body FROM chat_messages").scalars().all() == ["최근"]


# ---- 33번 WebSocket ----
# 연결과 API 요청이 같은 이벤트 루프에서 돌도록 화면 하나(`with`)에서 계정을 바꿔 가며 부른다


def closed_with(c, **kwargs):
    with (
        c.websocket_connect("/api/chats/ws", **kwargs) as ws,
        pytest.raises(WebSocketDisconnect) as e,
    ):
        ws.receive_json()
    return e.value.code


def test_socket_receives_message(pair):
    _, _, a, v = pair
    with make_client() as c:
        login(c, "victim1")
        with c.websocket_connect("/api/chats/ws", headers=ORIGIN) as ws:
            ws.send_text("무시되는 내용")
            login(c, "admin1")
            sent = c.post(f"/api/chats/{v}/messages", json={"body": "안녕하세요"}).json()
            event = ws.receive_json()
    assert event == {"type": "message", "peer_user_id": a, "message": {**sent, "mine": False}}


def test_socket_echoes_to_my_other_tab(pair):
    _, _, _, v = pair
    with make_client() as c:
        login(c, "admin1")
        with c.websocket_connect("/api/chats/ws", headers=ORIGIN) as ws:
            sent = c.post(f"/api/chats/{v}/messages", json={"body": "안녕하세요"}).json()
            assert ws.receive_json() == {"type": "message", "peer_user_id": v, "message": sent}


def test_socket_rejects_other_origin_and_no_session(pair):
    with make_client() as c:
        assert closed_with(c, headers=ORIGIN) == chat_hub.CLOSE_NO_SESSION
        login(c, "admin1")
        assert (
            closed_with(c, headers={"origin": "http://evil.example"}) == chat_hub.CLOSE_BAD_ORIGIN
        )
        assert closed_with(c) == chat_hub.CLOSE_BAD_ORIGIN  # Origin 없음
        # 로컬 모드는 Flutter 개발 서버(다른 포트)를 받는다
        with c.websocket_connect("/api/chats/ws", headers={"origin": "http://localhost:5555"}):
            pass


def test_socket_closed_on_logout(pair):
    with make_client() as c:
        login(c, "admin1")
        with c.websocket_connect("/api/chats/ws", headers=ORIGIN) as ws:
            assert c.post("/api/auth/logout").status_code == 204
            with pytest.raises(WebSocketDisconnect) as e:
                ws.receive_json()
    assert e.value.code == chat_hub.CLOSE_NO_SESSION


def test_socket_keeps_three_connections(pair):
    with make_client() as c:
        login(c, "admin1")
        with (
            c.websocket_connect("/api/chats/ws", headers=ORIGIN) as first,
            c.websocket_connect("/api/chats/ws", headers=ORIGIN),
            c.websocket_connect("/api/chats/ws", headers=ORIGIN),
            c.websocket_connect("/api/chats/ws", headers=ORIGIN),
            pytest.raises(WebSocketDisconnect) as e,
        ):
            first.receive_json()
    assert e.value.code == chat_hub.CLOSE_TOO_MANY
    assert chat_hub._connections == {}  # 끊긴 연결은 목록에 남지 않는다
