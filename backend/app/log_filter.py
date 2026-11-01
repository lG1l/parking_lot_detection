import logging


class HideSecretsFilter(logging.Filter):
    """uvicorn 접근 로그에서 쿼리 문자열(sig 등)을 지운다 (D-78)."""

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn은 (클라이언트 주소, 메서드, 경로+쿼리, HTTP 버전, 상태 코드)를 넘긴다
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            args = list(record.args)
            args[2] = str(record.args[2]).split("?", 1)[0]
            record.args = tuple(args)
        return True


def install_log_filter() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, HideSecretsFilter) for f in access.filters):
        access.addFilter(HideSecretsFilter())
