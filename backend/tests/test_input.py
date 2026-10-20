import copy
import threading

import pytest

from local import fake_worker
from tests.conftest import STORAGE, make_client
from tests.test_fake_worker import job_row
from tests.test_uploads import login, queue_files
from tests.test_videos import add_still, add_video, sql, user_id

BOX = [100, 100, 500, 400]  # det 1
GOOD = {
    "still_frame_id": 1,
    "schema_version": 5,
    "vehicle": {"det_id": 1},
    "damage": {
        "visible": True,
        "damage_bbox": [150, 150, 300, 300],
        "floor_corners": [[100, 600], [700, 600], [800, 900], [50, 900]],
        "damage_edges": [0, 1],
    },
}


@pytest.fixture
def me(client):
    login(client)
    return user_id()


@pytest.fixture
def ready(me):
    """사용자 입력을 기다리는 영상(stage1_done)."""
    vid, job = add_video(me, status="stage1_done")
    sql("UPDATE videos SET width = 1920, height = 1080 WHERE id = :v", v=vid)
    add_still(job, vid, [{"det_id": 1, "bbox": BOX, "conf": 0.9}])
    still = sql("SELECT id FROM still_frames WHERE analysis_job_id = :j", j=job).scalar_one()
    body = copy.deepcopy(GOOD)
    body["still_frame_id"] = still
    return vid, job, body


def login_again(client):
    body = {"login_id": "demo", "password": "demo-password"}
    assert client.post("/api/auth/login", json=body).status_code == 200
    return client


def put(client, vid, body):
    return client.put(f"/api/videos/{vid}/input", json=body)


def test_valid_input_is_stored_and_queued(client, ready):
    vid, job, body = ready
    body["damage"]["description"] = "문 쪽 긁힘"
    r = put(client, vid, body)
    assert r.status_code == 200 and r.json() == {"status": "stage1_done", "input_done": True}
    assert sql("SELECT input_completed_at FROM analysis_jobs WHERE id = :j", j=job).scalar_one()
    assert sql("SELECT payload FROM vehicle_selections").scalar_one() == {
        "det_id": 1,
        "bbox": BOX,
    }
    stored = sql("SELECT payload FROM damage_inputs").scalar_one()
    assert stored["description"] == "문 쪽 긁힘" and "photo_key" not in stored
    assert [p.name.endswith("-stage2.json") for p in queue_files()] == [True]


def set_path(body, path, value):
    target = body
    for key in path[:-1]:
        target = target[key]
    if value is KeyError:
        del target[path[-1]]
    else:
        target[path[-1]] = value


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (["schema_version"], 4),
        (["unknown"], 1),
        (["vehicle", "det_id"], 99),
        (["vehicle", "det_id"], "1"),
        (["damage", "visible"], "yes"),
        (["damage", "visible"], KeyError),
        (["damage", "damage_bbox"], [150, 150, 300]),
        (["damage", "damage_bbox"], [150, 150, 300.5, 300]),
        (["damage", "damage_bbox"], [150, 150, 2000, 300]),
        (["damage", "damage_bbox"], [90, 150, 300, 300]),  # 차량 밖
        (["damage", "damage_bbox"], [300, 150, 150, 300]),
        (["damage", "description"], ""),
        (["damage", "description"], "가" * 501),
        (["damage", "description"], None),
        (["damage", "photo_key"], "videos/999/inputs/photo.jpg"),
        (["damage", "photo_key"], "../x.jpg"),
        (["damage", "floor_corners"], [[0, 0], [1, 1], [2, 2]]),
        (["damage", "floor_corners"], [[0, 0], [0, 0], [5, 9], [9, 5]]),
        (["damage", "floor_corners"], [[0, 0], [5000, 0], [9, 9], [1, 9]]),
        (["damage", "floor_corners"], [[0, 0], [10, 10], [10, 0], [0, 10]]),  # 꼬임
        (["damage", "damage_edges"], []),
        (["damage", "damage_edges"], [0, 2]),
        (["damage", "damage_edges"], [1, 1]),
        (["damage", "damage_edges"], [4]),
        (["damage", "damage_edges"], [0, 1, 2]),
    ],
)
def test_invalid_input_is_422(client, ready, path, value):
    vid, _, body = ready
    set_path(body, path, value)
    r = put(client, vid, body)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "VALIDATION_FAILED"
    assert sql("SELECT count(*) FROM vehicle_selections").scalar_one() == 0
    assert queue_files() == []


def test_neighbor_edges_including_wraparound(client, ready):
    vid, _, body = ready
    body["damage"]["damage_edges"] = [3, 0]
    assert put(client, vid, body).status_code == 200


def test_other_still_frame_is_422(client, ready, me):
    vid, _, body = ready
    other_vid, other_job = add_video(me, "b.mp4", "stage1_done")
    add_still(other_job, other_vid)
    body["still_frame_id"] = sql(
        "SELECT id FROM still_frames WHERE analysis_job_id = :j", j=other_job
    ).scalar_one()
    assert put(client, vid, body).status_code == 422


def test_photo_key_of_this_video_is_accepted(client, ready):
    vid, _, body = ready
    body["damage"]["photo_key"] = f"videos/{vid}/inputs/photo.heic"
    assert put(client, vid, body).status_code == 200
    assert sql("SELECT payload FROM damage_inputs").scalar_one()["photo_key"].endswith("heic")


def test_second_save_is_409(client, ready):
    vid, _, body = ready
    assert put(client, vid, body).status_code == 200
    r = put(client, vid, body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"
    assert len(queue_files()) == 1


def test_wrong_state_is_409(client, me):
    vid, _ = add_video(me, status="queued")
    r = put(client, vid, GOOD)
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"


def test_raw_expired_is_checked_first(client, me):
    vid, _ = add_video(me, status="stage1_done", completed_days_ago=31)
    r = put(client, vid, GOOD)
    assert r.status_code == 409 and r.json()["error"]["code"] == "RAW_EXPIRED"


def test_other_users_video_is_404(client, me):
    other = sql(
        "INSERT INTO users (login_id, password_hash, name) VALUES ('o','x','o') RETURNING id"
    ).scalar_one()
    vid, _ = add_video(other, status="stage1_done")
    assert put(client, vid, GOOD).status_code == 404
    assert (
        client.post(
            f"/api/videos/{vid}/input/photo", json={"filename": "a.jpg", "size_bytes": 1}
        ).status_code
        == 404
    )


def test_login_required(client):
    assert client.put("/api/videos/1/input", json=GOOD).status_code == 401
    assert client.post("/api/videos/1/input/photo", json={}).status_code == 401


def test_queue_failure_rolls_back_input(me, ready, monkeypatch):
    vid, job, body = ready
    client = login_again(make_client(raise_server_exceptions=False))

    def boom(*_):
        raise RuntimeError("queue down")

    monkeypatch.setattr("app.jobs.send_job", boom)
    r = client.put(f"/api/videos/{vid}/input", json=body)
    assert r.status_code == 500
    assert sql("SELECT count(*) FROM damage_inputs").scalar_one() == 0
    assert (
        sql("SELECT input_completed_at FROM analysis_jobs WHERE id = :j", j=job).scalar_one()
        is None
    )


def test_concurrent_saves_yield_one_success(me, ready):
    vid, _, body = ready
    clients = [login_again(make_client()) for _ in range(2)]
    codes = []

    def call(c):
        codes.append(put(c, vid, body).status_code)

    threads = [threading.Thread(target=call, args=(c,)) for c in clients]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [200, 409]
    assert len(queue_files()) == 1
    assert sql("SELECT count(*) FROM vehicle_selections").scalar_one() == 1


def test_saved_input_lets_worker_reach_exhausted(client, ready, monkeypatch):
    vid, job, body = ready
    monkeypatch.setattr(fake_worker, "STEP_SECONDS", 0)
    assert put(client, vid, body).status_code == 200
    worker = fake_worker.Worker("zero_candidates", step=False)
    assert worker.poll_once() is True
    assert job_row(job).status == "exhausted"


# ---- API 18 ----


def photo(client, vid, filename="a.JPG", size=1000):
    return client.post(
        f"/api/videos/{vid}/input/photo", json={"filename": filename, "size_bytes": size}
    )


def test_photo_url_has_fixed_key_and_accepts_overwrite(client, ready):
    vid, *_ = ready
    r = photo(client, vid)
    assert r.status_code == 200
    key = r.json()["photo_key"]
    assert key == f"videos/{vid}/inputs/photo.jpg"
    url = r.json()["upload_url"].replace("http://testserver", "")
    assert client.put(url, content=b"one").status_code == 200  # If-None-Match 없이도
    url2 = photo(client, vid).json()["upload_url"].replace("http://testserver", "")
    assert client.put(url2, content=b"two").status_code == 200
    assert (STORAGE / "raw" / key).read_bytes() == b"two"


def test_photo_local_put_rejects_over_20mb(client, ready):
    vid, *_ = ready
    url = photo(client, vid).json()["upload_url"].replace("http://testserver", "")
    r = client.put(url, content=b"x" * (20 * 1024**2 + 1))
    assert r.status_code == 413


@pytest.mark.parametrize(
    ("filename", "size", "status", "code"),
    [
        ("a.gif", 10, 422, "UNSUPPORTED_FILE_TYPE"),
        ("noext", 10, 422, "UNSUPPORTED_FILE_TYPE"),
        ("a.png", 20 * 1024**2 + 1, 422, "FILE_TOO_LARGE"),
        ("", 10, 422, "VALIDATION_FAILED"),
        ("a.png", 0, 422, "VALIDATION_FAILED"),
        ("a.png", -1, 422, "VALIDATION_FAILED"),
    ],
)
def test_photo_validation(client, ready, filename, size, status, code):
    vid, *_ = ready
    r = photo(client, vid, filename, size)
    assert r.status_code == status and r.json()["error"]["code"] == code


@pytest.mark.parametrize("ext", ["jpg", "jpeg", "png", "heic", "PNG"])
def test_photo_extensions(client, ready, ext):
    vid, *_ = ready
    assert photo(client, vid, f"x.{ext}").json()["photo_key"].endswith(ext.lower())


def test_photo_state_errors(client, me):
    queued, _ = add_video(me, status="queued")
    assert photo(client, queued).json()["error"]["code"] == "INVALID_STATE"
    expired, _ = add_video(me, status="stage1_done", completed_days_ago=31)
    assert photo(client, expired).json()["error"]["code"] == "RAW_EXPIRED"


def test_photo_after_input_saved_is_409(client, ready):
    vid, _, body = ready
    put(client, vid, body)
    assert photo(client, vid).json()["error"]["code"] == "INVALID_STATE"
