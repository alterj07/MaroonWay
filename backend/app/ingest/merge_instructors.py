"""Put each instructor's ratings back on the row that teaches their classes.

    python -m app.ingest.merge_instructors --dry-run
    python -m app.ingest.merge_instructors

The instructors table holds the same person twice. The Registrar's grade
reports name them "CANTU J", RateMyProfessors names them "Justin Cantu", and
A&M's class schedule names them "Justin Colt Cantu" -- three spellings, three
canonical keys, three rows. The scheduler reads the row the class schedule
created, so the rating sitting on one of the others is invisible: 4,023
instructors carried an A&M person id and 3,467 carried an RMP id, and only 291
carried both.

The ingest cannot repair this. It attaches an id to a row and then skips that
person forever after (``if person_id in by_person: continue``), so re-running
it changes nothing -- the wrong rows are already claimed. The repair has to
look at the whole table at once, which is what this does.

Nothing is merged on a guess. A pair is merged only when it is unique in both
directions: exactly one unidentified row answers to this instructor's name,
*and* that row answers to no other instructor. "KIM J" fits ten people in the
Fall 2026 schedule, so "KIM J" is merged into none of them -- one person's
ratings shown under another person's name is worse than a blank.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from app.ingest.common import bump_data_version, configure_logging, session_scope
from app.services.identity import names_agree, read_name

log = logging.getLogger("ingest.merge_instructors")


@dataclass(frozen=True, slots=True)
class Row:
    """One row of the instructors table, as the planner needs it."""

    id: int
    full_name: str
    person_id: int | None = None
    rmp_id: int | None = None
    department: str | None = None
    basis: str | None = None
    confidence: float | None = None

    @property
    def identified(self) -> bool:
        """Whether A&M's class schedule knows who this is.

        These are the rows ``sections.instructor_id`` points at, so these are
        the rows a student's schedule actually reads.
        """
        return self.person_id is not None


@dataclass(frozen=True, slots=True)
class Merge:
    """Fold ``drop`` into ``keep``, and why that is safe."""

    keep: int
    drop: int
    reason: str


@dataclass(slots=True)
class Plan:
    merges: list[Merge]
    #: Identified rows whose name fits several unidentified rows, or whose
    #: counterpart fits several of them. Left alone on purpose.
    contested: int = 0
    #: Identified rows with nobody to merge -- genuinely new instructors, or
    #: ones we hold no history for.
    alone: int = 0
    #: Pairs refused because both rows already carry a different RMP profile.
    #: One of the two links is wrong and is already being shown to students,
    #: so these are listed rather than merely counted.
    conflicts: list[tuple[Row, Row]] = field(default_factory=list)
    unreadable: int = 0

    @property
    def conflicting(self) -> int:
        return len(self.conflicts)


def plan_merges(rows: list[Row]) -> Plan:
    """Decide which rows are the same person. No I/O, so it is testable.

    Both sides must be unique. A one-way check is not enough: an abbreviated
    name like "KIM J" fits many full names, and a full name may fit several
    abbreviations once middle names are involved. Requiring the pairing to be
    the only one either row has is what keeps a namesake's rating off someone
    else's schedule.
    """
    identified = [r for r in rows if r.identified]
    loose = [r for r in rows if not r.identified]

    by_surname: dict[str, list[Row]] = defaultdict(list)
    for row in loose:
        name = read_name(row.full_name)
        if name is not None:
            by_surname[name.surname].append(row)

    plan = Plan(merges=[])

    # Who fits whom, both ways round, before anything is decided.
    fits: dict[int, list[Row]] = {}
    claimants: dict[int, int] = defaultdict(int)
    for row in identified:
        ours = read_name(row.full_name)
        if ours is None:
            plan.unreadable += 1
            continue
        matches = [
            other
            for other in by_surname.get(ours.surname, ())
            if (theirs := read_name(other.full_name)) is not None and names_agree(ours, theirs)
        ]
        fits[row.id] = matches
        for other in matches:
            claimants[other.id] += 1

    for row in identified:
        matches = fits.get(row.id)
        if matches is None:
            continue
        if not matches:
            plan.alone += 1
            continue
        if len(matches) > 1:
            plan.contested += 1
            continue
        other = matches[0]
        if claimants[other.id] > 1:
            # They are this instructor's only candidate, but not only this
            # instructor's: an abbreviated name shared by several people.
            plan.contested += 1
            continue
        if row.rmp_id is not None and other.rmp_id is not None and row.rmp_id != other.rmp_id:
            plan.conflicts.append((row, other))
            continue
        plan.merges.append(
            Merge(row.id, other.id, f"{other.full_name!r} is the only {row.full_name!r}")
        )
    return plan


# --- the database half --------------------------------------------------------

_LOAD = text(
    """
    select id, full_name, person_id, rmp_id, department,
           rmp_match_basis, rmp_match_confidence
    from instructors
    """
)

#: Children keyed partly on instructor_id: repointing one onto a row that
#: already has the equivalent row would break the constraint, so the duplicate
#: is left behind and removed with its old parent. ``is not distinct from``
#: matches the schema's ``unique nulls not distinct``.
_CHILDREN_WITH_KEYS = {
    "course_grades": ("course_id", "term", "section"),
    "summaries": ("subject_type", "course_id", "prompt_version"),
    "instructor_traits": ("course_id", "question_version"),
    "instructor_course_terms": ("course_id", "term"),
}

#: Children where instructor_id is not part of any unique key.
_CHILDREN_PLAIN = ("sections", "name_links")


def _repoint_guarded(table: str, columns: tuple[str, ...]) -> Any:
    matching = " and ".join(f"k.{c} is not distinct from t.{c}" for c in columns)
    return text(
        f"""
        update {table} t set instructor_id = m.keep_id
        from merge_map m
        where t.instructor_id = m.drop_id
          and not exists (
              select 1 from {table} k
              where k.instructor_id = m.keep_id and {matching}
          )
        """
    )


_CREATE_MAP = text(
    """
    create temporary table merge_map (
        keep_id    bigint primary key,
        drop_id    bigint not null unique,
        rmp_id     bigint,
        department text,
        basis      text,
        confidence numeric(4, 3)
    ) on commit drop
    """
)

_FILL_MAP = text(
    """
    insert into merge_map (keep_id, drop_id, rmp_id, department, basis, confidence)
    values (:keep_id, :drop_id, :rmp_id, :department, :basis, :confidence)
    """
)

#: The dropped row goes first. ``instructors.rmp_id`` is unique and not
#: deferrable, so the id cannot be written onto the surviving row while the
#: old row still holds it -- which is why the map carries the value across.
_DROP = text("delete from instructors i using merge_map m where i.id = m.drop_id")

_ADOPT = text(
    """
    update instructors i
       set rmp_id               = coalesce(i.rmp_id, m.rmp_id),
           department           = coalesce(i.department, m.department),
           rmp_match_basis      = coalesce(i.rmp_match_basis, m.basis),
           rmp_match_confidence = coalesce(i.rmp_match_confidence, m.confidence)
    from merge_map m
    where i.id = m.keep_id
    """
)

_SHAPE = text(
    """
    select count(*)                                                          as total,
           count(person_id)                                                  as teaching,
           count(rmp_id)                                                     as rated,
           count(*) filter (where person_id is not null and rmp_id is not null) as both
    from instructors
    """
)

_PRODUCT = text(
    """
    select s.term,
           count(*)                                        as schedulable,
           count(*) filter (where i.rmp_id is not null)    as with_rating,
           count(*) filter (where i.id is null)            as no_instructor
    from sections s
    left join instructors i on i.id = s.instructor_id
    where s.meets <> '[]'::jsonb
    group by s.term
    order by s.term
    """
)


async def _report(session: Any, heading: str) -> None:
    shape = (await session.execute(_SHAPE)).first()
    log.info(
        "%s: %d instructors | %d teaching | %d rated | %d both",
        heading, shape.total, shape.teaching, shape.rated, shape.both,
    )
    for row in (await session.execute(_PRODUCT)).all():
        share = row.with_rating / row.schedulable if row.schedulable else 0.0
        log.info(
            "  %-12s %6d schedulable sections | %6d with a rating (%.1f%%) | %d with nobody",
            row.term, row.schedulable, row.with_rating, share * 100, row.no_instructor,
        )


async def run(*, dry_run: bool, limit: int | None = None) -> Plan:
    async with session_scope() as session:
        await _report(session, "before")

        rows = [
            Row(
                id=int(r.id),
                full_name=r.full_name,
                person_id=int(r.person_id) if r.person_id is not None else None,
                rmp_id=int(r.rmp_id) if r.rmp_id is not None else None,
                department=r.department,
                basis=r.rmp_match_basis,
                confidence=float(r.rmp_match_confidence)
                if r.rmp_match_confidence is not None
                else None,
            )
            for r in (await session.execute(_LOAD)).all()
        ]
        plan = plan_merges(rows)
        by_id = {r.id: r for r in rows}

        log.info(
            "%d rows can be merged | %d left alone as ambiguous | %d have no counterpart "
            "| %d disagree on which RMP profile | %d unreadable names",
            len(plan.merges), plan.contested, plan.alone, plan.conflicting, plan.unreadable,
        )
        would_gain = sum(
            1 for m in plan.merges
            if by_id[m.keep].rmp_id is None and by_id[m.drop].rmp_id is not None
        )
        log.info("%d of those put a rating on a row that teaches classes", would_gain)
        for merge in plan.merges[:10]:
            keep, drop = by_id[merge.keep], by_id[merge.drop]
            log.info(
                "  keep %-34s (person %s) <- %-28s (rmp %s)",
                keep.full_name, keep.person_id, drop.full_name, drop.rmp_id,
            )

        # One of each pair is linked to the wrong professor, and the one on the
        # teaching row is already being shown to students. Listed in full
        # because 26 rows is a morning's work to check by hand and a wrong
        # rating under a real person's name is the thing we must not ship.
        if plan.conflicts:
            log.warning(
                "%d instructors are linked to two different RateMyProfessors "
                "profiles -- one of each pair is wrong:",
                len(plan.conflicts),
            )
            for keep, drop in plan.conflicts:
                log.warning(
                    "  %-34s teaches, and is rmp %-9s | %-28s is rmp %s",
                    keep.full_name, keep.rmp_id, drop.full_name, drop.rmp_id,
                )

        if dry_run:
            log.info("dry run: nothing written")
            return plan
        if not plan.merges:
            log.info("nothing to merge")
            return plan

        merges = plan.merges[:limit] if limit else plan.merges
        await session.execute(_CREATE_MAP)
        await session.execute(
            _FILL_MAP,
            [
                {
                    "keep_id": m.keep,
                    "drop_id": m.drop,
                    "rmp_id": by_id[m.drop].rmp_id,
                    "department": by_id[m.drop].department,
                    "basis": by_id[m.drop].basis,
                    "confidence": by_id[m.drop].confidence,
                }
                for m in merges
            ],
        )
        for table, columns in _CHILDREN_WITH_KEYS.items():
            moved = (await session.execute(_repoint_guarded(table, columns))).rowcount
            log.info("moved %d %s rows", moved, table)
        for table in _CHILDREN_PLAIN:
            moved = (
                await session.execute(
                    text(
                        f"update {table} t set instructor_id = m.keep_id "
                        "from merge_map m where t.instructor_id = m.drop_id"
                    )
                )
            ).rowcount
            log.info("moved %d %s rows", moved, table)

        await session.execute(_DROP)
        await session.execute(_ADOPT)
        await session.commit()

        version = await bump_data_version(session)
        log.info("merged %d instructors; data_version now %d", len(merges), version)
        await _report(session, "after")
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report and write nothing")
    parser.add_argument("--limit", type=int, default=None, help="merge only the first N")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    asyncio.run(run(dry_run=args.dry_run, limit=args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
