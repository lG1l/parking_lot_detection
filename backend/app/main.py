from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import auth, batches, cases, inputs, local_routes, pins, retry, uploads, videos
from app.config import get_settings
from app.errors import install_error_handlers
from app.log_filter import install_log_filter

# 갱신 스크립트가 web.tar.gz를 여기에 푼다 (D-154). 로컬은 Flutter 개발 서버를 쓰므로 없다.
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app() -> FastAPI:
    settings = get_settings()  # 설정이 틀리면 여기서 시작을 멈춘다
    app = FastAPI(title="Parking Lot Incident Finder API")
    install_error_handlers(app)
    install_log_filter()
    app.include_router(auth.router)
    app.include_router(cases.router)
    app.include_router(uploads.router)
    app.include_router(videos.router)
    app.include_router(inputs.router)
    app.include_router(batches.router)
    app.include_router(pins.router)
    app.include_router(retry.router)
    if settings.app_mode == "local":  # 배포 서버에는 로컬 파일 경로를 열지 않는다 (D-158)
        app.include_router(local_routes.router)
        app.add_middleware(local_routes.LocalCors)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    # 화면 파일은 API와 같은 서버에서 준다 (D-11). 라우터보다 뒤에 둬야 /api/*가 먼저 처리된다.
    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

    return app


app = create_app()
