"""Async engine and session — the only place the API touches a connection pool.

ARCHITECTURE.md 5: the request path reads precomputed rows and nothing else. No
module under `pvmaps.api` opens its own engine, and nothing here imports pvlib,
rasterio, shapely or torch (tests/test_architecture.py enforces that).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

__all__ = ["SessionFactory", "create_engine", "session_scope"]

SessionFactory = async_sessionmaker[AsyncSession]


def create_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """One engine per process.

    `pool_pre_ping` because the demo database is a container that may have been
    restarted between rehearsals, and a stale connection surfacing as a 500 on
    the first judged request is not a risk worth the microsecond.
    """
    return create_async_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        # Precomputed reads are small; a long-lived connection is the common case.
        pool_recycle=1800,
    )


def create_session_factory(engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def session_scope(factory: SessionFactory) -> AsyncIterator[AsyncSession]:
    """Commit on success, roll back on anything else."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
