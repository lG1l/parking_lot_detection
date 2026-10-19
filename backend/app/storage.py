import hashlib
import hmac
import time
from pathlib import Path

import boto3
from botocore.config import Config

from app.config import get_settings

UPLOAD_URL_SECONDS = 900  # 01장 1.6, D-41
MAX_UPLOAD_BYTES = 5 * 1024**3  # 01장 1.6, D-22


def storage_root() -> Path:
    settings = get_settings()
    if settings.local_storage_dir:
        return Path(settings.local_storage_dir)
    return Path(__file__).resolve().parents[2] / "local_storage"


def _signature(method: str, area: str, key: str, exp: int) -> str:
    message = f"{method}\n{area}\n{key}\n{exp}".encode()
    secret = get_settings().local_url_secret.encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def verify_local_signature(method: str, area: str, key: str, exp: int, sig: str) -> bool:
    if exp < time.time():
        return False
    return hmac.compare_digest(_signature(method, area, key, exp), sig)


def make_upload_url(key: str) -> str:
    """원본 버킷에 PUT할 주소. AWS는 presigned URL, 로컬은 백엔드가 서명한 주소 (D-158)."""
    settings = get_settings()
    if settings.app_mode == "local":
        exp = int(time.time()) + UPLOAD_URL_SECONDS
        sig = _signature("PUT", "raw", key, exp)
        return f"{settings.local_base_url}/_local/raw/{key}?exp={exp}&sig={sig}"
    # 지역 주소를 직접 지정한다. 기본값은 전역 주소라 새 버킷에서 리디렉션이 나온다
    s3 = boto3.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=f"https://s3.{settings.aws_region}.amazonaws.com",
        config=Config(s3={"addressing_style": "virtual"}),
    )
    return s3.generate_presigned_url(
        "put_object",
        # IfNoneMatch는 서명에 들어가, 이미 있는 객체를 덮어쓰지 못하게 한다 (D-100)
        Params={
            "Bucket": f"{settings.s3_bucket_prefix}-raw",
            "Key": key,
            "IfNoneMatch": "*",
        },
        ExpiresIn=UPLOAD_URL_SECONDS,
    )
