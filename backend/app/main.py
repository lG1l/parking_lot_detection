from fastapi import FastAPI

from app import auth, local_routes, uploads, videos
from app.config import get_settings
from app.errors import install_error_handlers
from app.log_filter import install_log_filter


def create_app() -> FastAPI:
    settings = get_settings()  # 설정이 틀리면 여기서 시작을 멈춘다
    app = FastAPI(title="Parking Lot Incident Finder API")
    install_error_handlers(app)
    install_log_filter()
    app.include_router(auth.router)
    app.include_router(uploads.router)
    app.include_router(videos.router)
    if settings.app_mode == "local":  # 배포 서버에는 로컬 파일 경로를 열지 않는다 (D-158)
        app.include_router(local_routes.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
