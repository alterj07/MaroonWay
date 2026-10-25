"""Shared plumbing for the ingest jobs."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import make_engine, make_session_factory


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """One engine, one session, disposed on exit."""
    settings = get_settings()
    engine = make_engine(settings)
    factory = make_session_factory(engine)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


async def bump_data_version(session: AsyncSession) -> int:
    """Invalidate every cache key in one step.

    The API puts this number in every cache key, so a running server starts
    serving the new data within its version-check interval without a restart.
    """
    row = (
        await session.execute(
            text(
                """
                insert into data_version (id, version)
                values (1, 1)
                on conflict (id) do update
                    set version = data_version.version + 1, updated_at = now()
                returning version
                """
            )
        )
    ).first()
    await session.commit()
    return int(row[0]) if row else 0


def split_sql(script: str) -> Iterator[str]:
    """Split a .sql file into statements.

    Handles line comments and single-quoted strings. It does not handle
    dollar-quoted function bodies -- our schema has none, and this is a loader,
    not a migration tool.
    """
    statement: list[str] = []
    in_string = False
    index = 0
    length = len(script)

    while index < length:
        char = script[index]
        if in_string:
            statement.append(char)
            if char == "'":
                if index + 1 < length and script[index + 1] == "'":
                    statement.append(script[index + 1])
                    index += 2
                    continue
                in_string = False
            index += 1
            continue
        if char == "'":
            in_string = True
            statement.append(char)
            index += 1
            continue
        if char == "-" and script.startswith("--", index):
            newline = script.find("\n", index)
            index = length if newline == -1 else newline + 1
            statement.append("\n")
            continue
        if char == ";":
            chunk = "".join(statement).strip()
            if chunk:
                yield chunk
            statement = []
            index += 1
            continue
        statement.append(char)
        index += 1

    chunk = "".join(statement).strip()
    if chunk:
        yield chunk
