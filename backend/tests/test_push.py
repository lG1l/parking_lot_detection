import base64
import json

import pytest
from pywebpush import WebPushException

from app import push
from app.config import get_settings
from tests.conftest import make_client
from tests.test_videos import add_video, sign_in, sql


def b64(n):
    return base64.urlsafe_b64encode(b"\x04" + b"\x01" * (n - 1)).rstrip(b"=").decode()


def sub_body(endpoint="https://fcm.googleapis.com/fcm/send/abc", p256dh=None, auth=None):
    return {"endpoint": endpoint, "keys": {"p256dh": p256dh or b64(65), "auth": auth or b64(16)}}


@pytest.fixture
def vapid(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "vapid_private_key", "priv")
    monkeypatch.setattr(s, "vapid_public_key", "BPUB")
    monkeypatch.setattr(s, "vapid_subject", "https://localhost")


@pytest.fixture
def sent(monkeypatch, vapid):
    """webpush 대신 보낸 내용을 모은다. responses에 endpoint별 실패 상태를 넣을 수 있다."""

    class Calls(list):
        pass

    calls = Calls()
    responses = calls.responses = {}

    def fake(subscription_info, data, **kw):
        calls.append((subscription_info["endpoint"], json.loads(data), kw))
        status = responses.get(subscription_info["endpoint"])
        if status:
            resp = type("R", (), {"status_code": status})()
            raise WebPushException("fail", response=resp)

    monkeypatch.setattr(push, "webpush", fake)
    return calls


def subscribe(login_id, endpoint):
    c = sign_in(make_client(), login_id)
    assert c.put("/api/push/subscription", json=sub_body(endpoint)).status_code == 204
    return c


def code(r):
    return r.status_code, r.json()["error"]["code"]


@pytest.fixture
def case_id():
    from tests.test_videos import setup_case

    return setup_case()


# ---- 39번 공개 키 ----


def test_public_key_null_without_keys(client):
    assert client.get("/api/push/public-key").json() == {"public_key": None}


def test_public_key_when_configured(client, vapid):
    assert client.get("/api/push/public-key").json() == {"public_key": "BPUB"}


# ---- 40번 구독 저장 ----


def test_subscription_requires_login(client):
    assert code(client.put("/api/push/subscription", json=sub_body())) == (401, "UNAUTHENTICATED")


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://fcm.googleapis.com/fcm/send/x",
        "https://updates.push.services.mozilla.com/wpush/v2/x",
        "https://web.push.apple.com/x",
        "https://wns2-par02p.notify.windows.com/w/?token=x",
    ],
)
def test_allowed_endpoints(endpoint):
    assert push.allowed_endpoint(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/x",  # https 아님
        "https://fcm.googleapis.com.evil.example/x",  # 포함만 함
        "https://evilfcm.googleapis.com/x",
        "https://notify.windows.com/x",
        "https://evil-notify.windows.com/x",
        "https://fcm.googleapis.com:8443/x",  # 포트
        "https://user@fcm.googleapis.com/x",
        "https://169.254.169.254/latest/meta-data/",
        "https://[::1/x",
        "fcm.googleapis.com/x",
    ],
)
def test_rejected_endpoints(endpoint):
    assert not push.allowed_endpoint(endpoint)


def test_subscription_rejects_bad_endpoint_and_keys(case_id):
    c = sign_in(make_client(), "admin1")
    bad = [
        sub_body("https://169.254.169.254/"),
        sub_body(p256dh=b64(64)),
        sub_body(auth=b64(17)),
        sub_body(auth="!!!"),
    ]
    for body in bad:
        assert code(c.put("/api/push/subscription", json=body)) == (422, "VALIDATION_FAILED")
    assert sql("SELECT count(*) FROM push_subscriptions").scalar_one() == 0


def test_same_endpoint_moves_to_new_session(case_id):
    first = subscribe("admin1", "https://fcm.googleapis.com/fcm/send/a")
    first.post("/api/auth/logout")
    subscribe("victim1", "https://fcm.googleapis.com/fcm/send/a")
    rows = sql(
        "SELECT s.user_id FROM push_subscriptions p JOIN sessions s ON s.id = p.session_id"
    ).all()
    victim = sql("SELECT id FROM users WHERE login_id = 'victim1'").scalar_one()
    assert rows == [(victim,)]


def test_logout_deletes_subscription(case_id):
    c = subscribe("admin1", "https://fcm.googleapis.com/fcm/send/a")
    c.post("/api/auth/logout")
    assert sql("SELECT count(*) FROM push_subscriptions").scalar_one() == 0


# ---- 보내기 (주기 작업) ----

A = "https://fcm.googleapis.com/fcm/send/admin"
V = "https://fcm.googleapis.com/fcm/send/victim"


@pytest.fixture
def both(case_id):
    subscribe("admin1", A)
    subscribe("victim1", V)
    return case_id


def finish_stage2(job_id, minutes_ago=0):
    sql(
        "UPDATE analysis_jobs SET status = 'ready', "
        "stage2_ended_at = now() - make_interval(mins => :m) WHERE id = :j",
        j=job_id,
        m=minutes_ago,
    )


def test_done_goes_to_admin_and_victim_once(both, sent):
    vid, job = add_video(both, "secret_name.mp4", "stage2_running")
    finish_stage2(job)
    push.send_pending()
    push.send_pending()
    got = sorted((e, d["body"]) for e, d, _ in sent)
    assert got == [(A, "결과를 확인해 주세요."), (V, "관리자와 함께 결과를 확인할 수 있습니다.")]
    for _, data, kw in sent:
        assert data["url"] == f"/#/videos/{vid}"
        assert "secret_name" not in json.dumps(data, ensure_ascii=False)
        assert kw["ttl"] == 86400 and kw["vapid_claims"] == {"sub": "https://localhost"}


def test_old_event_is_not_sent(both, sent):
    _, job = add_video(both, "a.mp4", "stage2_running")
    finish_stage2(job, minutes_ago=11)
    push.send_pending()
    assert sent == []


def test_failed_resent_after_retry_fails_again(both, sent):
    _, job = add_video(both, "a.mp4", "stage1_running")
    sql("UPDATE analysis_jobs SET status = 'failed' WHERE id = :j", j=job)
    push.send_pending()
    assert {d["title"] for _, d, _ in sent} == {"영상을 분석하지 못했습니다"}
    assert len(sent) == 2
    sql("UPDATE analysis_jobs SET status = 'queued' WHERE id = :j", j=job)
    sql("UPDATE analysis_jobs SET status = 'failed' WHERE id = :j", j=job)
    push.send_pending()
    assert len(sent) == 4


def test_upload_unconfirmed_goes_to_admin_only(both, sent):
    vid, _ = add_video(both, "a.mp4", created_minutes_ago=31)
    add_video(both, "b.mp4", created_minutes_ago=29)  # 아직 업로드 중
    add_video(both, "c.mp4", created_minutes_ago=41)  # 10분보다 오래됨
    push.send_pending()
    assert [(e, d["url"]) for e, d, _ in sent] == [(A, f"/#/videos/{vid}")]


def test_victim_needs_accepted_and_not_deleted_case(case_id, sent):
    subscribe("admin1", A)
    subscribe("victim1", V)
    sql("UPDATE cases SET accepted_at = NULL WHERE id = :c", c=case_id)
    _, job = add_video(case_id, "a.mp4", "stage2_running")
    finish_stage2(job)
    push.send_pending()
    assert [e for e, _, _ in sent] == [A]

    sql("UPDATE cases SET accepted_at = now(), admin_deleted_at = now() WHERE id = :c", c=case_id)
    _, job = add_video(case_id, "b.mp4", "stage2_running")
    finish_stage2(job)
    push.send_pending()
    assert [e for e, _, _ in sent] == [A, V]


def test_expired_session_is_skipped(both, sent):
    sql("UPDATE sessions SET expires_at = now() - interval '1 second'")
    _, job = add_video(both, "a.mp4", "stage2_running")
    finish_stage2(job)
    push.send_pending()
    assert sent == []


def test_gone_subscription_is_deleted_and_others_still_sent(both, sent, caplog):
    sent.responses[A] = 410
    sent.responses[V] = 500
    _, job = add_video(both, "a.mp4", "stage2_running")
    finish_stage2(job)
    push.send_pending()
    assert len(sent) == 2
    endpoints = sql("SELECT endpoint FROM push_subscriptions").scalars().all()
    assert endpoints == [V]
    assert "push send failed: status 500" in caplog.text
    assert V not in caplog.text


def test_nothing_sent_without_keys(both, monkeypatch):
    calls = []
    monkeypatch.setattr(push, "webpush", lambda *a, **k: calls.append(a))
    _, job = add_video(both, "a.mp4", "stage2_running")
    finish_stage2(job)
    push.send_pending()
    assert calls == [] and sql("SELECT count(*) FROM push_events").scalar_one() == 0
