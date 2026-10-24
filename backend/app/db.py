"""Async engine and session plumbing.

The engine is created in the app lifespan and parked on ``app.state`` rather than
a module global, so tests can stand up their own.
"""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings


def make_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_pre_ping=True,
        # Harmless on the session pooler, required on the transaction one: in
        # transaction mode asyncpg's prepared statement cache outlives the
        # connection it was built for and raises
        # DuplicatePreparedStatementError. Off by default so either pooler works.
        connect_args={"statement_cache_size": 0},
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding one session per request."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session
