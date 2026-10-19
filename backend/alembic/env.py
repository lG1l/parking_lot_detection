from sqlalchemy import create_engine

from alembic import context
from app.config import get_settings

# 자동 생성(autogenerate)은 쓰지 않는다 (D-151). 변경은 op.execute에 SQL로 쓴다.
if context.is_offline_mode():
    context.configure(url=get_settings().database_url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(get_settings().database_url)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
