from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args, future=True)


def make_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def create_tables(engine) -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_schema(engine)


def _ensure_sqlite_schema(engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "batch_items" not in table_names:
        return
    existing = {column["name"] for column in inspector.get_columns("batch_items")}
    nullable_columns = {
        "stock": "INTEGER",
        "preparation_days": "INTEGER",
        "weight_grams": "INTEGER",
        "package_weight_grams": "INTEGER",
        "unit_quantity": "INTEGER",
    }
    with engine.begin() as connection:
        for name, column_type in nullable_columns.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE batch_items ADD COLUMN {name} {column_type}"))


def session_scope(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
