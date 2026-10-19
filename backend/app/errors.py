from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_CODE_BY_STATUS = {
    401: "UNAUTHENTICATED",
    404: "NOT_FOUND",
    409: "INVALID_STATE",
    422: "VALIDATION_FAILED",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


def _body(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    def _api_error(_: Request, exc: ApiError):
        return _body(exc.status, exc.code, exc.message)

    @app.exception_handler(StarletteHTTPException)
    def _http_error(_: Request, exc: StarletteHTTPException):
        code = _CODE_BY_STATUS.get(exc.status_code, "INTERNAL_ERROR")
        return _body(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    def _validation_error(_: Request, exc: RequestValidationError):
        # 입력값(비밀번호 등)이 로그·응답에 퍼지지 않게 위치만 적는다
        where = ", ".join(".".join(str(p) for p in e["loc"]) for e in exc.errors())
        return _body(422, "VALIDATION_FAILED", f"invalid value: {where}")

    @app.exception_handler(Exception)
    def _unexpected(_: Request, exc: Exception):
        return _body(500, "INTERNAL_ERROR", "internal error")
