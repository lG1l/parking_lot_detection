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
    r = admin.post("/api/cases", json={"victim_login_id": "vic\u0000tim1", "case_name": "사건"})
    assert (r.status_code, r.json()["error"]["code"]) == (422, "VALIDATION_FAILED")


def test_lookup_and_create_hide_admin_accounts():
    admin = login("admin1", "admin", "관리자")
    make_user(login_id="admin2", name="다른관리자", role="admin")
    for login_id in ["admin2", "ghost"]:
        r = admin.get("/api/users/lookup", params={"login_id": login_id})
        assert (r.status_code, r.json()["error"]["code"]) == (422, "INVITEE_INVALID")
        r = admin.post("/api/cases", json={"victim_login_id": login_id, "case_name": "사건"})
        assert (r.status_code, r.json()["error"]["code"]) == (422, "INVITEE_INVALID")
    assert actions() == ["login"]


def test_create_case_and_list_for_both_accounts():
    admin = login("admin1", "admin", "관리자")
    victim = login("victim1", "victim", "홍길동")
    first = admin.post("/api/cases", json={"victim_login_id": "victim1", "case_name": "사건"})
    second = admin.post(
        "/api/cases", json={"victim_login_id": "victim1", "case_name": "사건"}
    )  # 다시 초대하면 새 사건
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
    admin.post("/api/cases", json={"victim_login_id": "victim1", "case_name": "사건"})
    other = login("victim2", "victim", "이순")
    assert other.get("/api/cases").json() == {"items": []}


def test_victim_cannot_lookup_or_create():
    victim = login("victim1", "victim")
    r = victim.get("/api/users/lookup", params={"login_id": "victim1"})
    assert (r.status_code, r.json()["error"]["code"]) == (403, "ROLE_NOT_ALLOWED")
    r = victim.post("/api/cases", json={"victim_login_id": "victim1", "case_name": "사건"})
    assert (r.status_code, r.json()["error"]["code"]) == (403, "ROLE_NOT_ALLOWED")


def test_case_apis_require_login(client):
    assert client.get("/api/cases").status_code == 401
    assert (
        client.post("/api/cases", json={"victim_login_id": "x", "case_name": "사건"}).status_code
        == 401
    )
    assert client.get("/api/users/lookup", params={"login_id": "x"}).status_code == 401


def test_empty_values_are_422():
    admin = login("admin1", "admin")
    assert admin.get("/api/users/lookup", params={"login_id": ""}).status_code == 422
    assert admin.get("/api/users/lookup").status_code == 422
    assert (
        admin.post("/api/cases", json={"victim_login_id": "", "case_name": "사건"}).status_code
        == 422
    )


def test_accept_case_shows_videos_to_victim():
    from tests.test_uploads import new_video

    admin = login("admin1", "admin", "관리자")
    victim = login("victim1", "victim", "홍길동")
    case_id = admin.post(
        "/api/cases", json={"victim_login_id": "victim1", "case_name": "사건"}
    ).json()["id"]
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
    case_id = admin.post(
        "/api/cases", json={"victim_login_id": "victim1", "case_name": "사건"}
    ).json()["id"]
    other = login("victim2", "victim", "이순")
    for path in [f"/api/cases/{case_id}/accept", "/api/cases/999999/accept"]:
        r = other.post(path)
        assert (r.status_code, r.json()["error"]["code"]) == (404, "CASE_NOT_FOUND")
    r = admin.post(f"/api/cases/{case_id}/accept")
    assert (r.status_code, r.json()["error"]["code"]) == (403, "ROLE_NOT_ALLOWED")
    assert "accept_case" not in actions()


def test_accept_requires_login(client):
    assert client.post("/api/cases/1/accept").status_code == 401


def new_case(admin, name="홍길동 11/5"):
    return admin.post("/api/cases", json={"victim_login_id": "victim1", "case_name": name}).json()[
        "id"
    ]


def items(c):
    return c.get("/api/cases").json()["items"]


def test_case_name_is_per_account():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    admin = login("admin1", "admin", "관리자")
    victim = login("victim1", "victim", "홍길동")
    case_id = new_case(admin, "  홍길동 11/5  ")
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    assert items(admin)[0]["case_name"] == "홍길동 11/5"  # 앞뒤 공백을 지운다
    assert items(victim)[0]["case_name"] == f"{today} 연결"

    victim.post(f"/api/cases/{case_id}/accept")
    r = victim.patch(f"/api/cases/{case_id}", json={"case_name": "B2주차장 사고"})
    assert r.status_code == 200
    assert r.json()["case_name"] == "B2주차장 사고" and r.json()["id"] == case_id
    assert items(victim)[0]["case_name"] == "B2주차장 사고"
    assert items(admin)[0]["case_name"] == "홍길동 11/5"  # 상대 이름은 그대로

    r = admin.patch(f"/api/cases/{case_id}", json={"case_name": "11월 접촉"})
    assert r.status_code == 200
    assert items(admin)[0]["case_name"] == "11월 접촉"
    assert items(victim)[0]["case_name"] == "B2주차장 사고"


@pytest.mark.parametrize("name", ["", "   ", "가" * 51, "a\u0000b", None])
def test_invalid_case_name_is_422(name):
    admin = login("admin1", "admin", "관리자")
    make_user(login_id="victim1", name="홍길동", role="victim")
    case_id = new_case(admin)
    body = {} if name is None else {"case_name": name}
    r = admin.post("/api/cases", json={"victim_login_id": "victim1", **body})
    assert (r.status_code, r.json()["error"]["code"]) == (422, "VALIDATION_FAILED")
    r = admin.patch(f"/api/cases/{case_id}", json=body)
    assert (r.status_code, r.json()["error"]["code"]) == (422, "VALIDATION_FAILED")


def test_case_name_50_chars_is_ok():
    admin = login("admin1", "admin", "관리자")
    make_user(login_id="victim1", name="홍길동", role="victim")
    new_case(admin, "가" * 50)
    assert items(admin)[0]["case_name"] == "가" * 50


def test_delete_hides_case_only_for_that_account():
    from tests.test_uploads import new_video, presign

    admin = login("admin1", "admin", "관리자")
    victim = login("victim1", "victim", "홍길동")
    case_id = new_case(admin)
    video_id = new_video(admin, case_id)
    victim.post(f"/api/cases/{case_id}/accept")

    assert admin.delete(f"/api/cases/{case_id}").status_code == 204
    assert items(admin) == [] and admin.get("/api/videos").json() == []
    r = admin.get(f"/api/videos/{video_id}")
    assert (r.status_code, r.json()["error"]["code"]) == (404, "VIDEO_NOT_FOUND")
    # 숨긴 사건에는 더 올릴 수 없고, 다시 지우거나 이름을 바꿔도 없는 사건이다
    r = presign(admin, case_id)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "CASE_NOT_FOUND")
    r = admin.post(f"/api/videos/{video_id}/upload/complete")
    assert (r.status_code, r.json()["error"]["code"]) == (404, "VIDEO_NOT_FOUND")
    for r in [
        admin.delete(f"/api/cases/{case_id}"),
        admin.patch(f"/api/cases/{case_id}", json={"case_name": "x"}),
    ]:
        assert (r.status_code, r.json()["error"]["code"]) == (404, "CASE_NOT_FOUND")

    # 피해자에게는 그대로 보인다
    assert [i["id"] for i in items(victim)] == [case_id]
    assert victim.get(f"/api/videos/{video_id}").status_code == 200

    assert victim.delete(f"/api/cases/{case_id}").status_code == 204
    assert items(victim) == [] and victim.get("/api/videos").json() == []
    # 행과 영상은 남는다(30일 파기 일정을 따른다). 이름 수정·삭제는 access_logs에 남기지 않는다
    with get_engine().connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM videos WHERE id = :v"), {"v": video_id}
            ).scalar()
            == 1
        )
    assert "delete_case" not in actions() and "rename_case" not in actions()


def test_rename_delete_other_or_unaccepted_case_is_404():
    admin = login("admin1", "admin", "관리자")
    victim = login("victim1", "victim", "홍길동")
    case_id = new_case(admin)
    other_admin = login("admin2", "admin", "다른관리자")
    other_victim = login("victim2", "victim", "이순")
    calls = [
        (other_admin, case_id),
        (other_victim, case_id),
        (victim, case_id),  # 수락 전
        (admin, 999999),
    ]
    for c, cid in calls:
        for r in [
            c.delete(f"/api/cases/{cid}"),
            c.patch(f"/api/cases/{cid}", json={"case_name": "x"}),
        ]:
            assert (r.status_code, r.json()["error"]["code"]) == (404, "CASE_NOT_FOUND")
    assert items(admin)[0]["case_name"] == "홍길동 11/5"


def test_rename_delete_require_login(client):
    assert client.patch("/api/cases/1", json={"case_name": "x"}).status_code == 401
    assert client.delete("/api/cases/1").status_code == 401
