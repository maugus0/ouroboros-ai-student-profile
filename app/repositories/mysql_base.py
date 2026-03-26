"""Base repository with common async database operations (raw SQL, aiomysql)."""

from typing import Any

import aiomysql

from app.core.logging import get_logger
from app.repositories.db_pool import get_pool

logger = get_logger(__name__)


class MySQLBaseRepository:
    """Base class for MySQL repositories using raw SQL with aiomysql."""

    async def execute_query(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Execute a SELECT query and return results as list of dicts."""
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(query, params)
                return await cursor.fetchall()

    async def execute_one(self, query: str, params: tuple = ()) -> dict[str, Any] | None:
        """Execute a SELECT query and return a single result."""
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(query, params)
                return await cursor.fetchone()

    async def execute_write(self, query: str, params: tuple = ()) -> int:
        """Execute an INSERT/UPDATE/DELETE and return affected row count."""
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, params)
                await conn.commit()
                return cursor.rowcount

    async def execute_insert(self, query: str, params: tuple = ()) -> int:
        """Execute an INSERT and return the last inserted ID."""
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, params)
                await conn.commit()
                return cursor.lastrowid
