import json
import logging
import os
import time

import boto3

from app.config import get_settings
from app.storage import storage_root

logger = logging.getLogger(__name__)

KINDS = ("stage1", "stage2", "next_batch")  # 04장 4.6


def send_job(job_id: int, kind: str) -> None:
    """분석 대기열에 작업을 넣는다. AWS는 SQS, 로컬은 폴더 큐 (D-159)."""
    if kind not in KINDS:
        raise ValueError(f"unknown job kind: {kind}")
    message = json.dumps({"job_id": job_id, "kind": kind})
    settings = get_settings()
    if settings.app_mode == "aws":
        sqs = boto3.client("sqs", region_name=settings.aws_region)
        sqs.send_message(QueueUrl=settings.sqs_queue_url, MessageBody=message)
        return
    queue_dir = storage_root() / "scratch" / "backend" / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns() // 1_000_000}-{job_id}-{kind}.json"
    tmp = queue_dir / f".{name}.tmp"
    tmp.write_text(message)
    os.replace(tmp, queue_dir / name)  # 반쯤 쓴 파일을 워커가 읽지 않도록 이름을 바꿔 완성한다


def start_gpu() -> None:
    """GPU EC2 켜기를 요청한다. 실패해도 호출한 API는 성공으로 답한다 (D-42)."""
    settings = get_settings()
    if settings.app_mode == "local":
        return
    try:
        ec2 = boto3.client("ec2", region_name=settings.aws_region)
        ec2.start_instances(InstanceIds=[settings.gpu_instance_id])
    except Exception as exc:  # noqa: BLE001 - 켜기 실패가 API를 막으면 안 된다
        logger.error("gpu start failed: %s", type(exc).__name__)
