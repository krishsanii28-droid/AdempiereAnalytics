"""Read-only access to the insightai views."""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout

from .config import get_settings

log = logging.getLogger("insightai.db")


class DatabaseUnavailable(Exception):
    """The database could not be reached or the query did not finish in time."""


_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        s = get_settings()
        _pool = ConnectionPool(
            kwargs={
                "host": s.db_host,
                "port": s.db_port,
                "dbname": s.db_name,
                "user": s.db_user,
                "password": s.db_password,
                "connect_timeout": 5,
                "application_name": "insightai",
                "autocommit": True,
                "row_factory": dict_row,
                # The role already has these defaults; repeating them means a mis-set role cannot widen access.
                "options": (
                    "-c default_transaction_read_only=on "
                    f"-c statement_timeout={s.statement_timeout_ms} "
                    "-c search_path=insightai "
                    "-c client_min_messages=warning"
                ),
            },
            min_size=1,
            max_size=s.pool_max,
            timeout=6,
            open=False,
        )
        _pool.open()
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def _plain(value: Any) -> Any:
    return float(value) if isinstance(value, Decimal) else value


def query(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run one parameterised SELECT and return rows as plain dicts."""
    try:
        with _get_pool().connection() as conn:
            rows = conn.execute(sql, params or {}).fetchall()
    except PoolTimeout as exc:
        log.error("database unavailable: no connection within the pool timeout")
        raise DatabaseUnavailable("The ADempiere database is not reachable.") from exc
    except psycopg.errors.QueryCanceled as exc:
        log.error("query cancelled by statement_timeout")
        raise DatabaseUnavailable("The query took too long and was cancelled.") from exc
    except psycopg.OperationalError as exc:
        # str(exc) can include the connection string; log the class only.
        log.error("database unavailable: %s", type(exc).__name__)
        raise DatabaseUnavailable("The ADempiere database is not reachable.") from exc
    return [{k: _plain(v) for k, v in row.items()} for row in rows]


def query_one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    rows = query(sql, params)
    return rows[0] if rows else {}
