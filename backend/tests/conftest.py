import os
import shutil
import tempfile
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from alembic import command

# 개발용 DB(app)를 지우지 않도록 테스트는 별도 DB를 쓴다. CI는 TEST_DATABASE_URL로 지정한다.
TEST_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://app:app@127.0.0.1:5432/app_test"
)
# app.main은 import할 때 설정을 읽으므로 먼저 넣는다
os.environ["APP_MODE"] = "local"
os.environ["DATABASE_URL"] = TEST_URL
os.environ["LOCAL_URL_SECRET"] = "0" * 64
# 파일 저장과 폴더 큐도 저장소의 local_storage/ 대신 임시 폴더에 만든다
# tests.conftest로 다시 import돼도 같은 폴더를 쓰도록 이미 정해졌으면 그 값을 쓴다
STORAGE = Path(os.environ.setdefault("LOCAL_STORAGE_DIR", tempfile.mkdtemp(prefix="test_storage_")))

BACKEND = Path(__file__).resolve().parent.parent
TABLES = (
    "users, sessions, upload_tokens, upload_agreements, videos, analysis_jobs, still_frames, "
    "vehicle_selections, damage_inputs, candidates, candidate_clips, pinned_incidents, access_logs"
)


@pytest.fixture(scope="session", autouse=True)
def _database():
    url = make_url(TEST_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def _clean_tables(_database):
    from app.db import get_engine

    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def _clean_storage():
    yield
    for child in STORAGE.iterdir():
        shutil.rmtree(child, ignore_errors=True)


def make_client(**kwargs):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app, client=("127.0.0.1", 50000), **kwargs)


@pytest.fixture
def client():
    return make_client()
