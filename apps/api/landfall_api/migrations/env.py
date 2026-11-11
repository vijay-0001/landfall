from alembic import context
from sqlalchemy import create_engine

url = context.config.get_main_option("sqlalchemy.url")

engine = create_engine(url, future=True)
with engine.connect() as conn:
    context.configure(connection=conn, target_metadata=None, version_table="alembic_version_app")
    with context.begin_transaction():
        context.run_migrations()
    conn.commit()
