import logging
import re

# 업로드 링크 token은 경로에 들어 있어 접근 로그에 그대로 찍힌다 (D-78)
_TOKEN = re.compile(r"(/api/uploads/)[^/?\s]+")


class HideSecretsFilter(logging.Filter):
    """uvicorn 접근 로그에서 경로의 token을 ***로 바꾸고 쿼리 문자열(sig 등)을 지운다."""

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn은 (클라이언트 주소, 메서드, 경로+쿼리, HTTP 버전, 상태 코드)를 넘긴다
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            path = str(record.args[2]).split("?", 1)[0]
            args = list(record.args)
            args[2] = _TOKEN.sub(r"\1***", path)
            record.args = tuple(args)
        return True


def install_log_filter() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, HideSecretsFilter) for f in access.filters):
        access.addFilter(HideSecretsFilter())
