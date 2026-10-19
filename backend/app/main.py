from fastapi import FastAPI

from app import auth
from app.config import get_settings
from app.errors import install_error_handlers


def create_app() -> FastAPI:
    get_settings()  # 설정이 틀리면 여기서 시작을 멈춘다
    app = FastAPI(title="Parking Lot Incident Finder API")
    install_error_handlers(app)
    app.include_router(auth.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
