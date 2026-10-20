import time

import pytest

from app import storage
from tests.conftest import STORAGE
from tests.test_uploads import login, new_link, presign


@pytest.fixture
def upload_url(client):
    login(client)
    token = new_link(client)
    url = presign(client, token).json()["upload_url"]
    return url.removeprefix("http://localhost:8000")


def put(client, path, data=b"video-bytes", **headers):
    return client.put(path, content=data, headers={"If-None-Match": "*", **headers})


def raw_files():
    return [p for p in (STORAGE / "raw").rglob("*") if p.is_file()]


def signed_path(key, exp=None):
    exp = exp or int(time.time()) + 900
    return f"/_local/raw/{key}?exp={exp}&sig={storage._signature('PUT', 'raw', key, exp)}"


def test_put_saves_file(client, upload_url):
    assert put(client, upload_url).status_code == 200
    files = raw_files()
    assert len(files) == 1 and files[0].read_bytes() == b"video-bytes"
    assert files[0].name == "original.mp4"


def test_put_requires_if_none_match(client, upload_url):
    r = client.put(upload_url, content=b"x")
    assert r.status_code == 403 and raw_files() == []


def test_put_cannot_overwrite(client, upload_url):
    assert put(client, upload_url).status_code == 200
    assert put(client, upload_url, data=b"other").status_code == 412
    assert raw_files()[0].read_bytes() == b"video-bytes"
    assert len(list((STORAGE / "raw").rglob("*.tmp"))) == 0


def test_put_rejects_bad_signature(client, upload_url):
    path, query = upload_url.split("?")
    wrong = "1" if query.endswith("0") else "0"  # 마지막 글자가 원래와 다르게 한다
    assert put(client, f"{path}?{query[:-1]}{wrong}").status_code == 403
    assert put(client, f"{path.replace('videos/', 'videos/9')}?{query}").status_code == 403
    assert raw_files() == []


def test_put_rejects_expired_url(client):
    assert (
        put(client, signed_path("videos/1/original.mp4", exp=int(time.time()) - 1)).status_code
        == 403
    )


def test_put_stops_at_size_limit(client, monkeypatch):
    monkeypatch.setattr(storage, "MAX_UPLOAD_BYTES", 10)
    r = put(client, signed_path("videos/1/original.mp4"), data=b"x" * 11)
    assert r.status_code == 413
    assert list((STORAGE / "raw").rglob("*")) == [] or all(
        p.is_dir() for p in (STORAGE / "raw").rglob("*")
    )


def test_put_blocks_path_escape(client):
    r = put(client, signed_path("../escape.mp4"))
    assert r.status_code in (403, 404)
    assert not (STORAGE / "escape.mp4").exists()
    r = put(client, signed_path("%2e%2e/escape.mp4").replace("%252e", "%2e"))
    assert r.status_code in (403, 404)
    assert not (STORAGE / "escape.mp4").exists()


def test_local_routes_absent_in_aws_mode(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main
    from app.config import Settings

    aws = Settings(
        app_mode="aws",
        database_url="postgresql+psycopg://x",
        aws_region="ap-northeast-2",
        s3_bucket_prefix="p",
        sqs_queue_url="q",
        gpu_instance_id="i",
    )
    monkeypatch.setattr(main, "get_settings", lambda: aws)
    app = main.create_app()
    r = TestClient(app).put(signed_path("videos/1/original.mp4"), content=b"x")
    assert r.status_code == 404
    assert not any(getattr(r, "path", "").startswith("/_local") for r in app.routes)
