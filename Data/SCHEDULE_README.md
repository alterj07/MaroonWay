# Spring 2027 schedule collector

The section feed is the same public Howdy endpoint used by TAMU's class search.
No sign-in, private student records, or registration operations are used.

## Outputs

- `output/spring_2027_sections.csv`: one row per term + CRN. This is the schedule file.
- `output/spring_2027_office_hours.csv`: the same section identifiers with office-hour evidence and lookup status.
- `output/spring_2027_report.json`: counts, coverage, service errors, and limitations.

`meetings_json` retains every meeting (lecture/lab/etc.), days, 24-hour local start/end
times, date range, building, and room. A missing time is NOT proof of asynchronous
delivery. `is_online` is blank when the instruction description does not resolve it.
`open_seats` is a point-in-time Y/N indicator; the public feed does not expose exact
seat counts. `fetched_at` records when the source snapshot was saved.

`campus` is the section's published site. `term_campus` is the portal term label.
The College Station term includes other sites, which are retained and labeled.
Filter `campus` for physical location; `Unknown` must not silently become CStat.
Qatar has no separate Spring 2027 term in the retrieved term list, although individual
Qatar-site sections may appear in another term feed. Undergraduate/graduate level
is not explicitly supplied in this feed; do not silently infer eligibility from course number.

`instructors_json` supports multiple instructors. `grade_rmp_links_json` references
rows in the existing `schedule_dataset.csv` by campus, level, subject, course number,
and historical instructor name. Full RMP-name matches are preferred; surname/initial
matches are explicitly heuristic. Ambiguous and absent matches stay unresolved.
No RMP comments are duplicated into the section export.

`is_honors` uses the explicit Honors attribute. Prerequisites, reserved seats,
linked-section requirements, and registration eligibility still need separate validation.
For the minimum 20-minute rule, compare every timed meeting on overlapping dates
and weekdays. Do not treat a missing meeting time as proof that a section fits.

## Office hours

The public Simple Syllabus redirect is followed to its published document; only the
Instructor Details/Office Hours component is extracted, excluding university help
desk hours and other boilerplate. Term, course, and CRN are checked against the section.
The PDF rendering service sometimes fails while its public HTML document works;
the collector uses the document code from the public redirect and reads that HTML.
403/429 responses stop collection; no access controls are bypassed.

Statuses distinguish `not_checked`, `syllabus_unavailable`, `lookup_error`,
`not_stated`, `login_required` (e.g. See Canvas), `by_appointment`,
`published_text_needs_review`, and `source_mismatch_needs_review`.
`office_hours_text` and `office_location_text` are source text, not automatically
parsed weekly slots. `office_hours_instructor_evidence` preserves attribution,
including multiple instructors where present. `office_hours_term_status` confirms
the document's term only; it does not guarantee hours won't change.
`office_hours_usable_for_conflict_checks` stays false until a person validates and
structures the hours. Old-term office hours are never substituted.

Office-hour collection is separate from the complete section download and can take
hours across every section. Not-checked rows are not claims that no hours exist.
The collector stops on the first service error, preserves completed cache records,
and exports all schedules and collected hours anyway. Faculty-page discovery is
not automated; it is a manual fallback for selected professors with missing syllabi.

## Run from the Data folder

```sh
./venv/bin/python collect_spring_schedule.py
```

Builds from cached schedules; downloads a feed only if absent. To update schedules:

```sh
./venv/bin/python collect_spring_schedule.py --refresh-schedule
```

To look up the next 100 uncached office-hour entries, prioritizing CSCE and MATH:

```sh
./venv/bin/python collect_spring_schedule.py --office-hours 100 --office-subjects CSCE,MATH
```

To attempt all remaining section syllabi, use `--office-hours 25000`. This can be
slow and can stop early on a service error. Repeating a command resumes previously
successful results. Remove an individual office-hour cache only if you deliberately
want to recheck that source. No publishing, Git commit, or push occurs.

`--offline` rebuilds solely from caches. `--history PATH` selects a historical CSV.
`--output-dir PATH` keeps outputs somewhere else. Caches are under
`output/schedule_cache/`; do not delete them if you want to resume.

Dependencies: existing `requests` and `beautifulsoup4`; no new installation needed
in the project's existing environment. Tests: `./venv/bin/python -m unittest test_schedule_collector.py`.


## Prerequisites added

Use `output/spring_2027_sections_with_prerequisites.csv` for the enriched snapshot.
It has prerequisite_text, corequisite_text, status, source URL/term/timestamp,
and the full catalog narrative. Every section was matched against Howdy's Spring
2027 course catalog, including graduate courses. Missing narratives were checked
against Howdy's section prerequisite display. not_listed_in_catalog means only
that no prerequisite was listed; it is not proof of unrestricted eligibility.
Conditions such as minimum grades, OR alternatives, concurrent enrollment, major,
classification, and instructor permission are preserved as source text. These
are not machine-evaluated eligibility rules. Section overrides and linked-section
requirements still need separate checks.

The office-hours process launched before this update continues writing the original
CSV and separate office-hour CSV. It cannot overwrite the enriched snapshot. Join
newer office-hour results by term_code + crn. Future collector runs include the new
prerequisite columns and emit the enriched filename too. Do not start a second
collector against the same output directory while the previous one is running.
