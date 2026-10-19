import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

from app import storage
from app.errors import ApiError

router = APIRouter(prefix="/_local")


def _raw_path(key: str) -> Path:
    root = (storage.storage_root() / "raw").resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root):  # ../ 로 폴더 밖을 가리키는 키를 막는다
        raise ApiError(403, "FORBIDDEN", "invalid key")
    return path


# 본문을 조각으로 읽어야 해서 이 라우트만 async다. 파일 쓰기는 스레드풀에서 한다 (D-157과 같은 이유).
@router.put("/raw/{key:path}")
async def put_raw(key: str, request: Request, exp: int, sig: str):
    if not storage.verify_local_signature("PUT", "raw", key, exp, sig):
        raise ApiError(403, "FORBIDDEN", "invalid or expired signature")
    if request.headers.get("if-none-match") != "*":
        raise ApiError(403, "FORBIDDEN", "If-None-Match: * is required")
    final = _raw_path(key)
    if final.exists():
        raise ApiError(412, "PRECONDITION_FAILED", "object already exists")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > storage.MAX_UPLOAD_BYTES:
        raise ApiError(413, "TOO_LARGE", "object is too large")

    tmp_dir = final.parent
    await run_in_threadpool(tmp_dir.mkdir, parents=True, exist_ok=True)
    tmp = tmp_dir / f".{uuid.uuid4().hex}.tmp"
    received = 0
    try:
        with tmp.open("wb") as out:
            async for chunk in request.stream():
                received += len(chunk)
                if received > storage.MAX_UPLOAD_BYTES:
                    raise ApiError(413, "TOO_LARGE", "object is too large")
                await run_in_threadpool(out.write, chunk)
        try:
            os.link(tmp, final)  # 이미 있으면 실패해서 덮어쓰지 않는다
        except FileExistsError:
            raise ApiError(412, "PRECONDITION_FAILED", "object already exists") from None
    finally:
        tmp.unlink(missing_ok=True)
    return Response(status_code=200)
