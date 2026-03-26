"""
Async MySQL connection pool using aiomysql.
Raw SQL queries — no ORM.
"""

from dataclasses import dataclass

import aiomysql

from app.core.logging import get_logger

logger = get_logger(__name__)

_pool: aiomysql.Pool | None = None


@dataclass(frozen=True, slots=True)
class DatabasePoolConfig:
    """Parameters for creating the global aiomysql pool."""

    host: str
    port: int
    db: str
    user: str
    password: str
    pool_size: int = 10


async def create_pool(config: DatabasePoolConfig) -> aiomysql.Pool:
    """Create and cache a global connection pool."""
    global _pool  # pylint: disable=global-statement
    if _pool is not None:
        return _pool

    _pool = await aiomysql.create_pool(
        host=config.host,
        port=config.port,
        db=config.db,
        user=config.user,
        password=config.password,
        minsize=1,
        maxsize=config.pool_size,
        autocommit=True,
        charset="utf8mb4",
    )
    logger.info("database_pool_created", host=config.host, db=config.db, pool_size=config.pool_size)
    return _pool


def get_pool() -> aiomysql.Pool:
    """Return the global pool. Raises if not initialised."""
    if _pool is None:
        raise RuntimeError("Database pool has not been initialised. Call create_pool() first.")
    return _pool


async def close_pool() -> None:
    """Close the connection pool gracefully."""
    global _pool  # pylint: disable=global-statement
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None
        logger.info("database_pool_closed")
