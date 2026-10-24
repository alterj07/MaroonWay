"""Phase 0: look at the real CSV before writing anything that depends on it.

    python -m app.ingest.profile_csv /path/to/grades.csv

Prints every column with its inferred type, null count, distinct count and a few
sample values, then says which of our fields mapped, which did not, and -- the
question left open at planning time -- whether the file carries per-section
meeting times. Read-only: it never writes to the file or the database.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.ingest.columns import SCHEDULE_FIELDS, resolve_columns

SAMPLE_LIMIT = 5


@dataclass(slots=True)
class ColumnProfile:
    header: str
    total: int = 0
    nulls: int = 0
    ints: int = 0
    floats: int = 0
    distinct: Counter = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.distinct is None:
            self.distinct = Counter()

    def observe(self, value: str | None) -> None:
        self.total += 1
        text = (value or "").strip()
        if not text:
            self.nulls += 1
            return
        if len(self.distinct) < 10_000:
            self.distinct[text] += 1
        try:
            int(text)
            self.ints += 1
            return
        except ValueError:
            pass
        try:
            float(text)
            self.floats += 1
        except ValueError:
            pass

    @property
    def guessed_type(self) -> str:
        filled = self.total - self.nulls
        if filled == 0:
            return "empty"
        if self.ints == filled:
            return "int"
        if self.ints + self.floats == filled:
            return "float"
        return "text"

    @property
    def samples(self) -> list[str]:
        return [value for value, _ in self.distinct.most_common(SAMPLE_LIMIT)]


def profile(path: Path, row_limit: int | None, delimiter: str | None) -> int:
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        head = handle.read(8192)
        handle.seek(0)
        if delimiter is None:
            try:
                delimiter = csv.Sniffer().sniff(head, delimiters=",;\t|").delimiter
            except csv.Error:
                delimiter = ","
        reader = csv.DictReader(handle, delimiter=delimiter)
        headers = [h for h in (reader.fieldnames or []) if h is not None]
        if not headers:
            print(f"{path}: no header row found", file=sys.stderr)
            return 1

        profiles = {header: ColumnProfile(header) for header in headers}
        rows = 0
        for row in reader:
            rows += 1
            for header in headers:
                profiles[header].observe(row.get(header))
            if row_limit is not None and rows >= row_limit:
                break

    print(f"file        {path}")
    print(f"delimiter   {delimiter!r}")
    print(f"rows read   {rows}{' (limited)' if row_limit and rows >= row_limit else ''}")
    print(f"columns     {len(headers)}")
    print()
    width = max(len(h) for h in headers)
    print(f"{'column'.ljust(width)}  {'type':<6} {'nulls':>7} {'distinct':>9}  samples")
    print("-" * (width + 40))
    for header in headers:
        p = profiles[header]
        samples = ", ".join(s[:28] for s in p.samples)
        print(
            f"{header.ljust(width)}  {p.guessed_type:<6} {p.nulls:>7} "
            f"{len(p.distinct):>9}  {samples}"
        )

    column_map = resolve_columns(headers)
    print("\nmapped fields")
    for our_field, csv_header in sorted(column_map.fields.items()):
        print(f"  {our_field:<12} <- {csv_header}")
    if column_map.ambiguous:
        print("\nambiguous (first was used; set OVERRIDES in app/ingest/columns.py)")
        for our_field, hits in sorted(column_map.ambiguous.items()):
            print(f"  {our_field:<12} candidates: {', '.join(hits)}")
    if column_map.unmapped_headers:
        print("\nunmapped columns (add to FIELD_ALIASES or ignore)")
        for header in column_map.unmapped_headers:
            print(f"  {header}")
    if column_map.missing_required:
        print("\nMISSING REQUIRED: " + ", ".join(column_map.missing_required))
        print("  grades cannot load until these map; add them to OVERRIDES.")
    if not column_map.has_values:
        print("\nWARNING: no gpa or grade-count column mapped -- nothing to score with.")

    found_schedule = column_map.schedule_fields
    print("\nscheduling data")
    if found_schedule:
        print(f"  found: {', '.join(found_schedule)}")
        print("  -> sections can be loaded from this file (Phase 4 has real data).")
    else:
        print(f"  none of: {', '.join(SCHEDULE_FIELDS)}")
        print("  -> grades-only; the scheduler runs on tests/fixtures until a")
        print("     sections file exists. This is the question planning left open.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--rows", type=int, default=None, help="stop after N rows")
    parser.add_argument("--delimiter", default=None, help="override the sniffed delimiter")
    args = parser.parse_args(argv)
    if not args.path.is_file():
        print(f"not a file: {args.path}", file=sys.stderr)
        return 1
    return profile(args.path, args.rows, args.delimiter)


if __name__ == "__main__":
    raise SystemExit(main())
