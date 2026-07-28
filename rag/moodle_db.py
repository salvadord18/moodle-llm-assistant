"""Database adapter supporting PostgreSQL and MariaDB/MySQL."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from config import DatabaseSettings


def connect(settings: DatabaseSettings | None = None):
    settings = settings or DatabaseSettings.from_environment()
    if settings.dbtype == "pgsql":
        import psycopg2
        return psycopg2.connect(
            host=settings.host,
            port=settings.port,
            dbname=settings.name,
            user=settings.user,
            password=settings.password,
        )

    import pymysql
    return pymysql.connect(
        host=settings.host,
        port=settings.port,
        database=settings.name,
        user=settings.user,
        password=settings.password,
        charset="utf8mb4",
        autocommit=False,
    )


@contextmanager
def connection(settings: DatabaseSettings | None = None) -> Iterator[object]:
    current = connect(settings)
    try:
        yield current
    finally:
        current.close()
