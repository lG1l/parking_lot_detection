import pytest
from pydantic import ValidationError

from app.config import Settings

DB = "postgresql+psycopg://app:app@127.0.0.1:5432/app"


def make(**kw):
    return Settings(_env_file=None, **kw)


def test_app_mode_is_required(monkeypatch):
    monkeypatch.delenv("APP_MODE")
    with pytest.raises(ValidationError):
        make(database_url=DB)


def test_app_mode_rejects_unknown_value():
    with pytest.raises(ValidationError):
        make(app_mode="dev", database_url=DB)


def test_local_requires_long_secret():
    with pytest.raises(ValidationError):
        make(app_mode="local", database_url=DB, local_url_secret="short")


def test_aws_requires_aws_keys():
    with pytest.raises(ValidationError):
        make(app_mode="aws", database_url=DB)


def test_local_ok():
    assert make(app_mode="local", database_url=DB, local_url_secret="a" * 64).app_mode == "local"


AWS = {
    "app_mode": "aws",
    "database_url": DB,
    "aws_region": "ap-northeast-2",
    "s3_bucket_prefix": "p",
    "sqs_queue_url": "q",
    "gpu_instance_id": "i",
}


def test_aws_requires_long_origin_secret():
    with pytest.raises(ValidationError):
        make(**AWS, origin_verify_secret="short")
    assert make(**AWS, origin_verify_secret="a" * 32).app_mode == "aws"
