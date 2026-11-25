from functools import lru_cache
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_mode: Literal["local", "aws"]  # 기본값 없음 (D-158)
    database_url: str
    local_url_secret: str = ""
    local_base_url: str = "http://localhost:8000"
    local_storage_dir: str = ""  # 비면 저장소 루트의 local_storage/ (D-121)
    aws_region: str = ""
    s3_bucket_prefix: str = ""
    sqs_queue_url: str = ""
    gpu_instance_id: str = ""
    requeue_after_minutes: int = 10  # 멈춘 작업 재전송 기준 시간 (D-153)
    # 카카오 인증 (D-356). 셋 중 하나라도 비면 가입 시작(35번)이 503을 준다
    kakao_rest_api_key: str = ""
    kakao_client_secret: str = ""
    kakao_redirect_uri: str = ""
    # 웹 푸시 (D-358). 셋 중 하나라도 비면 보내지 않고 39번은 null을 준다
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_subject: str = ""
    # CloudFront가 원본 요청에 붙이는 비밀 헤더 X-Origin-Verify 값 (D-340). aws일 때 필수
    origin_verify_secret: str = ""

    @model_validator(mode="after")
    def _check_mode_keys(self) -> Self:
        if self.app_mode == "local":
            if len(self.local_url_secret) < 64:
                raise ValueError("LOCAL_URL_SECRET must be at least 64 characters in local mode")
        else:
            for key in ("aws_region", "s3_bucket_prefix", "sqs_queue_url", "gpu_instance_id"):
                if not getattr(self, key):
                    raise ValueError(f"{key.upper()} is required in aws mode")
            if len(self.origin_verify_secret) < 32:
                raise ValueError("ORIGIN_VERIFY_SECRET must be at least 32 characters in aws mode")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
