import os

# app.main은 import할 때 설정을 읽으므로 테스트 기본값을 먼저 넣는다
os.environ.setdefault("APP_MODE", "local")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://app:app@127.0.0.1:5432/app")
os.environ.setdefault("LOCAL_URL_SECRET", "0" * 64)
