"""ORM 会话与 SQLite 事务边界，统一业务数据访问。"""

import os
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterator, TypeVar

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, URL
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.database import database_path
from app.core.models import Base

Model = TypeVar("Model", bound=Base)


@lru_cache(maxsize=8)
def engine_for(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    engine = create_engine(URL.create('sqlite', database=str(path)),
                           connect_args={'timeout': 10}, poolclass=NullPool)

    @event.listens_for(engine, 'connect')
    def configure(dbapi_connection, _):
        # Python sqlite3 的隐式事务模式无法保证一致读快照，交由 SQLAlchemy 显式开始事务。
        dbapi_connection.isolation_level = None
        dbapi_connection.execute('PRAGMA foreign_keys = ON')
        dbapi_connection.execute('PRAGMA busy_timeout = 10000')
        if os.name != 'nt':
            os.chmod(path, 0o600)

    @event.listens_for(engine, 'begin')
    def begin(conn):
        conn.exec_driver_sql('BEGIN IMMEDIATE' if conn.get_execution_options().get('sqlite_write') else 'BEGIN')

    return engine


@contextmanager
def orm_session(*, write: bool = False) -> Iterator[Session]:
    # 每个请求使用独立连接；测试与切换实例不会复用另一数据库的会话。
    with engine_for(database_path().resolve()).connect().execution_options(sqlite_write=write) as conn:
        with Session(bind=conn, expire_on_commit=False) as session, session.begin():
            if write:
                from app.core.period_lock import write_boundary, validate_appended_dates
                boundary, heads = write_boundary(session)
                from sqlalchemy import select, func
                from app.core.models import StockMovement
                movement_head=session.scalar(select(func.max(StockMovement.id))) or 0
            yield session
            if write:
                session.flush()
                from app.inventory.lots import record_movements
                record_movements(session,movement_head)
                validate_appended_dates(session, boundary, heads)
                from app.finance.business_journals import validate_posted_sources
                validate_posted_sources(session)
                from app.finance.profit_transfers import validate_posted_sources as validate_transfers
                validate_transfers(session)


def model_data(model) -> dict:
    return {column.key: getattr(model, column.key) for column in model.__mapper__.columns}


def add_model(session: Session, model: Model) -> Model:
    # 主单和独立冲销需要编号后才能写入来源关系；刷新失败由外层事务整体回滚。
    session.add(model)
    session.flush()
    return model
