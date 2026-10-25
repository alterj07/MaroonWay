"""Keeping the cache in step with ingest runs."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app import repository
from app.cache import CacheRegistry


async def ensure_fresh(session: AsyncSession, caches: CacheRegistry) -> bool:
    """Adopt a new data version if one has landed. Returns True if it had.

    Rate-limited by the registry, so this is a no-op on almost every request.
    """
    if not caches.due_for_version_check():
        return False
    version = await repository.current_data_version(session)
    return await caches.set_data_version(version)
