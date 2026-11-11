import pytest
from sqlalchemy import text

from app.cases import mask_name
from app.db import get_engine
from tests.conftest import make_client
from tests.test_auth import make_user


def login(login_id, role, name="홍길동"):
    make_user(login_id=login_id, name=name, role=role)
    c = make_client()
    c.post("/api/auth/login", json={"login_id": login_id, "password": "demo-password"})
    return c


def actions():
    with get_engine().connect() as conn:
        return conn.execute(text("SELECT action FROM access_logs ORDER BY id")).scalars().all()


@pytest.mark.parametrize(
    "name,masked", [("홍길동", "홍*동"), ("이순", "이*"), ("남궁민수", "남**수"), ("김", "*")]
)
def test_mask_name(name, masked):
    assert mask_name(name) == masked


def test_lookup_shows_masked_name_and_logs():
    admin = login("admin1", "admin", "관리자")
    make_user(login_id="victim1", name="홍길동", role="victim")
    r = admin.get("/api/users/lookup", params={"login_id": "victim1"})
    assert r.status_code == 200
    assert r.json() == {"login_id": "victim1", "masked_name": "홍*동"}
    assert actions() == ["login", "lookup_invitee"]


def test_nul_in_login_id_is_422():
    admin = login("admin1", "admin", "관리자")
    r = admin.get("/api/users/lookup", params={"login_id": "vic\u0000tim1"})
    assert (r.status_code, r.json()["error"]["code"]) == (422, "VALIDATION_FAILED")
    r = admin.post("/api/cases", json={"victim_login_id": "vic\u0000tim1"})
    assert (r.status_code, r.json()["error"]["code"]) == (422, "VALIDATION_FAILED")


def test_lookup_and_create_hide_admin_accounts():
    admin = login("admin1", "admin", "관리자")
    make_user(login_id="admin2", name="다른관리자", role="admin")
    for login_id in ["admin2", "ghost"]:
        r = admin.get("/api/users/lookup", params={"login_id": login_id})
        assert (r.status_code, r.json()["error"]["code"]) == (422, "INVITEE_INVALID")
        r = admin.post("/api/cases", json={"victim_login_id": login_id})
        assert (r.status_code, r.json()["error"]["code"]) == (422, "INVITEE_INVALID")
    assert actions() == ["login"]


def test_create_case_and_list_for_both_accounts():
    admin = login("admin1", "admin", "관리자")
    victim = login("victim1", "victim", "홍길동")
    first = admin.post("/api/cases", json={"victim_login_id": "victim1"})
    second = admin.post("/api/cases", json={"victim_login_id": "victim1"})  # 다시 초대하면 새 사건
    assert first.status_code == 201
    assert first.json()["victim_name"] == "홍길동"
    assert second.json()["id"] != first.json()["id"]
    assert "create_case" in actions()

    expected = [second.json()["id"], first.json()["id"]]
    for c in [admin, victim]:
        items = c.get("/api/cases").json()["items"]
        assert [i["id"] for i in items] == expected
        assert items[0]["admin_name"] == "관리자" and items[0]["victim_name"] == "홍길동"


def test_cases_list_excludes_other_accounts_cases():
    admin = login("admin1", "admin", "관리자")
    make_user(login_id="victim1", name="홍길동", role="victim")
    admin.post("/api/cases", json={"victim_login_id": "victim1"})
    other = login("victim2", "victim", "이순")
    assert other.get("/api/cases").json() == {"items": []}


def test_victim_cannot_lookup_or_create():
    victim = login("victim1", "victim")
    r = victim.get("/api/users/lookup", params={"login_id": "victim1"})
    assert (r.status_code, r.json()["error"]["code"]) == (403, "ROLE_NOT_ALLOWED")
    r = victim.post("/api/cases", json={"victim_login_id": "victim1"})
    assert (r.status_code, r.json()["error"]["code"]) == (403, "ROLE_NOT_ALLOWED")


def test_case_apis_require_login(client):
    assert client.get("/api/cases").status_code == 401
    assert client.post("/api/cases", json={"victim_login_id": "x"}).status_code == 401
    assert client.get("/api/users/lookup", params={"login_id": "x"}).status_code == 401


def test_empty_values_are_422():
    admin = login("admin1", "admin")
    assert admin.get("/api/users/lookup", params={"login_id": ""}).status_code == 422
    assert admin.get("/api/users/lookup").status_code == 422
    assert admin.post("/api/cases", json={"victim_login_id": ""}).status_code == 422


def test_accept_case_shows_videos_to_victim():
    from tests.test_uploads import new_video

    admin = login("admin1", "admin", "관리자")
    victim = login("victim1", "victim", "홍길동")
    case_id = admin.post("/api/cases", json={"victim_login_id": "victim1"}).json()["id"]
    video_id = new_video(admin, case_id)  # 수락 전에도 관리자는 올릴 수 있다

    # 수락 전: 사건은 22번에 보이고(알림용), 영상은 보이지 않는다
    assert victim.get("/api/cases").json()["items"][0]["accepted_at"] is None
    assert victim.get("/api/videos").json() == []
    r = victim.get(f"/api/videos/{video_id}")
    assert (r.status_code, r.json()["error"]["code"]) == (404, "VIDEO_NOT_FOUND")
    assert [i["video_id"] for i in admin.get("/api/videos").json()] == [video_id]

    assert victim.post(f"/api/cases/{case_id}/accept").status_code == 204
    accepted_at = victim.get("/api/cases").json()["items"][0]["accepted_at"]
    assert accepted_at is not None
    assert [i["video_id"] for i in victim.get("/api/videos").json()] == [video_id]
    assert victim.get(f"/api/videos/{video_id}").status_code == 200

    # 다시 수락해도 204이고 시각·기록은 그대로다
    assert victim.post(f"/api/cases/{case_id}/accept").status_code == 204
    assert victim.get("/api/cases").json()["items"][0]["accepted_at"] == accepted_at
    assert actions().count("accept_case") == 1


def test_accept_other_case_is_404_and_admin_is_403():
    admin = login("admin1", "admin", "관리자")
    make_user(login_id="victim1", name="홍길동", role="victim")
    case_id = admin.post("/api/cases", json={"victim_login_id": "victim1"}).json()["id"]
    other = login("victim2", "victim", "이순")
    for path in [f"/api/cases/{case_id}/accept", "/api/cases/999999/accept"]:
        r = other.post(path)
        assert (r.status_code, r.json()["error"]["code"]) == (404, "CASE_NOT_FOUND")
    r = admin.post(f"/api/cases/{case_id}/accept")
    assert (r.status_code, r.json()["error"]["code"]) == (403, "ROLE_NOT_ALLOWED")
    assert "accept_case" not in actions()


def test_accept_requires_login(client):
    assert client.post("/api/cases/1/accept").status_code == 401
