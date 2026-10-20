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

    @model_validator(mode="after")
    def _check_mode_keys(self) -> Self:
        if self.app_mode == "local":
            if len(self.local_url_secret) < 64:
                raise ValueError("LOCAL_URL_SECRET must be at least 64 characters in local mode")
        else:
            for key in ("aws_region", "s3_bucket_prefix", "sqs_queue_url", "gpu_instance_id"):
                if not getattr(self, key):
                    raise ValueError(f"{key.upper()} is required in aws mode")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
