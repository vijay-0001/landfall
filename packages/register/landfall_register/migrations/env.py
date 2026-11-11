from alembic import context
from sqlalchemy import create_engine

config = context.config
url = config.get_main_option("sqlalchemy.url")


def run_migrations_online() -> None:
    engine = create_engine(url, future=True)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
        conn.commit()


run_migrations_online()
