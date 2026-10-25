"""Apply a .sql file to the configured database.

    python -m app.ingest.apply_sql sql/001_schema.sql sql/002_indexes.sql

Equivalent to pasting the file into the Supabase SQL editor, which is the other
(and, for a first run, more visible) option. There is no psql on this machine.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from sqlalchemy import text

from app.ingest.common import configure_logging, session_scope, split_sql

log = logging.getLogger("ingest.sql")


async def apply(paths: list[Path], *, dry_run: bool) -> int:
    statements: list[tuple[Path, str]] = []
    for path in paths:
        statements.extend((path, stmt) for stmt in split_sql(path.read_text()))

    if dry_run:
        for path, statement in statements:
            first_line = statement.strip().splitlines()[0]
            log.info("%s: %s", path.name, first_line[:100])
        log.info("%d statements (dry run, nothing applied)", len(statements))
        return 0

    async with session_scope() as session:
        for path, statement in statements:
            await session.execute(text(statement))
        await session.commit()
    log.info("applied %d statements", len(statements))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    import asyncio

    return asyncio.run(apply(args.paths, dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
