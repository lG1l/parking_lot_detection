import os
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app import storage
from app.errors import ApiError

router = APIRouter(prefix="/_local")

# S3 버킷 CORS와 같은 응답 헤더 (D-164 3번). 영역별로 메서드·요청 헤더가 다르다.
_CORS = {
    "/_local/raw/": ("PUT", "Content-Type, If-None-Match"),
    "/_local/masked/": ("GET", "Range"),
}


class LocalCors:
    """/_local/* 응답에만 CORS 헤더를 붙인다. 403·412 같은 오류 응답에도 붙여 프론트가 상태 코드를 읽는다."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        rule = None
        if scope["type"] == "http":
            rule = next((v for p, v in _CORS.items() if scope["path"].startswith(p)), None)
        if rule is None:
            await self.app(scope, receive, send)
            return
        methods, allow_headers = rule
        headers = [(b"access-control-allow-origin", b"*")]
        if scope["method"] == "OPTIONS":  # preflight는 라우트에 보내지 않고 여기서 답한다
            headers += [
                (b"access-control-allow-methods", methods.encode()),
                (b"access-control-allow-headers", allow_headers.encode()),
                (b"access-control-max-age", b"3600"),
                (b"content-length", b"0"),
            ]
            await send({"type": "http.response.start", "status": 204, "headers": headers})
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                message["headers"] = [*message["headers"], *headers]
            await send(message)

        await self.app(scope, receive, send_with_cors)


def _area_path(area: str, key: str) -> Path:
    root = (storage.storage_root() / area).resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root):  # ../ 로 폴더 밖을 가리키는 키를 막는다
        raise ApiError(403, "FORBIDDEN", "invalid key")
    return path


# 본문을 조각으로 읽어야 해서 이 라우트만 async다. 파일 쓰기는 스레드풀에서 한다 (D-157과 같은 이유).
@router.put("/raw/{key:path}")
async def put_raw(key: str, request: Request, exp: int, sig: str):
    if not storage.verify_local_signature("PUT", "raw", key, exp, sig):
        raise ApiError(403, "FORBIDDEN", "invalid or expired signature")
    # 파손 사진은 다시 올리면 덮어쓴다(05장 18번). 영상 원본은 덮어쓰지 못한다 (D-100)
    is_photo = re.fullmatch(storage.PHOTO_KEY_PATTERN, key) is not None
    limit = storage.MAX_PHOTO_BYTES if is_photo else storage.MAX_UPLOAD_BYTES
    if not is_photo and request.headers.get("if-none-match") != "*":
        raise ApiError(403, "FORBIDDEN", "If-None-Match: * is required")
    final = _area_path("raw", key)
    if not is_photo and final.exists():
        raise ApiError(412, "PRECONDITION_FAILED", "object already exists")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise ApiError(413, "TOO_LARGE", "object is too large")

    tmp_dir = final.parent
    await run_in_threadpool(tmp_dir.mkdir, parents=True, exist_ok=True)
    tmp = tmp_dir / f".{uuid.uuid4().hex}.tmp"
    received = 0
    try:
        with tmp.open("wb") as out:
            async for chunk in request.stream():
                received += len(chunk)
                if received > limit:
                    raise ApiError(413, "TOO_LARGE", "object is too large")
                await run_in_threadpool(out.write, chunk)
        if is_photo:
            os.replace(tmp, final)
        else:
            try:
                os.link(tmp, final)  # 이미 있으면 실패해서 덮어쓰지 않는다
            except FileExistsError:
                raise ApiError(412, "PRECONDITION_FAILED", "object already exists") from None
    finally:
        tmp.unlink(missing_ok=True)
    return Response(status_code=200)


# 원본(raw)을 읽는 라우트는 없다 (D-158 3번). 서명만 보고 소유권은 URL을 발급할 때 이미 확인했다.
@router.get("/masked/{key:path}")
def get_masked(key: str, exp: int, sig: str):
    if not storage.verify_local_signature("GET", "masked", key, exp, sig):
        raise ApiError(403, "FORBIDDEN", "invalid or expired signature")
    path = _area_path("masked", key)
    if not path.is_file():
        raise ApiError(404, "NOT_FOUND", "object not found")
    return FileResponse(path)  # Range 요청은 Starlette가 처리한다
