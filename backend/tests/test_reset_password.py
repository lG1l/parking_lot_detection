import sys

import pytest

from scripts import reset_password
from tests.conftest import make_client
from tests.test_auth import count, make_user


def run(monkeypatch, login_id, password):
    monkeypatch.setattr(sys, "argv", ["reset_password", "--login-id", login_id])
    monkeypatch.setattr(reset_password.getpass, "getpass", lambda prompt: password)
    reset_password.main()


def login(login_id, password):
    return make_client().post("/api/auth/login", json={"login_id": login_id, "password": password})


def test_changes_password_and_ends_sessions(monkeypatch, capsys):
    make_user("victim1", role="victim")
    make_user("other")
    assert login("victim1", "demo-password").status_code == 200
    assert login("other", "demo-password").status_code == 200

    run(monkeypatch, "victim1", "New-pass-2026")

    assert "password changed: victim1" in capsys.readouterr().out
    assert (
        count(
            "SELECT count(*) FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE u.login_id = 'victim1'"
        )
        == 0
    )
    assert count("SELECT count(*) FROM sessions") == 1  # 다른 계정 세션은 그대로
    assert login("victim1", "demo-password").status_code == 401
    assert login("victim1", "New-pass-2026").status_code == 200


@pytest.mark.parametrize(
    "login_id, password, message",
    [
        ("nobody", "x", "no such login id: nobody"),
        ("victim1", "", "password is empty"),
        ("victim1", "가" * 25, "password is longer than 72 bytes"),
    ],
)
def test_rejects(monkeypatch, login_id, password, message):
    make_user("victim1", role="victim")
    with pytest.raises(SystemExit) as exc:
        run(monkeypatch, login_id, password)
    assert str(exc.value) == message
    assert login("victim1", "demo-password").status_code == 200
