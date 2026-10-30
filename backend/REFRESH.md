# Refreshing the data

Run from `backend/`, with `DATABASE_URL` set in `backend/.env`. Every step has
a dry run; run it, read it, then run the real one. Nothing here needs a browser
or a logged-in session.

Steps 1–3 are the ones that close the missing-data gap. Steps 4–6 are the
RateMyProfessors half and are only worth running once that question is settled
(see **Before step 4**).

---

## 0. Check which database you are pointed at

```bash
cd backend
.venv/bin/python -c "from app.config import get_settings; u=get_settings().database_url; print(u.split('@')[-1])"
```

It prints the host only, never the password. Confirm it is the one you mean
before anything below writes.

## 1. Add the instructor id column

```bash
.venv/bin/python -m app.ingest.apply_sql sql/005_person_id.sql --dry-run
.venv/bin/python -m app.ingest.apply_sql sql/005_person_id.sql
```

Adds `instructors.person_id` plus two columns recording what an RMP link
rested on. Idempotent — safe to re-run.

## 2. Load the class schedule

This is the public TEC 51.974 feed: no login, no key, no scraping.

```bash
.venv/bin/python -m app.ingest.load_public_schedule --list-terms
.venv/bin/python -m app.ingest.load_public_schedule --term 202631 --dry-run
.venv/bin/python -m app.ingest.load_public_schedule --term 202631
.venv/bin/python -m app.ingest.load_public_schedule --term 202711
```

`202631` is Fall 2026 College Station, `202711` Spring 2027. Add `202632` /
`202712` for Galveston if you want it.

The dry run should say roughly `14350 usable; 0 without a course code`. If
"without a course code" is anything but 0, stop — the feed's shape has changed
and `tests/test_public_schedule.py` will say how.

**Check it landed:**

```sql
select term, count(*) sections,
       count(*) filter (where meets <> '[]'::jsonb) with_times,
       count(distinct instructor_id) instructors
from sections group by term order by term;

select count(*) total, count(person_id) with_person_id from instructors;
```

`with_person_id` is the number that matters. It should be in the low
thousands; it was 0 before this.

## 3. Rebuild the grade dataset with the new matcher

**This needs inputs that are not in the repository.** `build_dataset.py` reads
the cached Registrar PDFs from `Data/pdfs/` and the RateMyProfessors roster
from `Data/output/rmp_cache_v2/`, and neither is checked in -- the existing
`schedule_dataset.csv` was built on another machine (see `DATA_README.md`).
Without them the script fails either way: `--reparse` finds no PDFs, and
without it there is no `sections_campus_source.csv` to read.

So this step needs one of: the original machine's `Data/pdfs/` and
`Data/output/` caches copied across, or a full re-download
(`python3 build_dataset.py --fetch`, hours, and it hits RateMyProfessors).

Loading the CSV we already have does work, and takes a path:

```bash
.venv/bin/python -m app.ingest.load_rmp_dataset ../Data/output/schedule_dataset.csv --dry-run
.venv/bin/python -m app.ingest.load_rmp_dataset ../Data/output/schedule_dataset.csv
```

**Send me this**, it is the number the whole matcher change turns on:

```bash
python3 - <<'PY'
import csv; from collections import Counter
csv.field_size_limit(50_000_000)
c = Counter()
with open("Data/output/schedule_dataset.csv", newline="", encoding="utf-8") as fh:
    for row in csv.DictReader(fh): c[row.get("match_status") or "(blank)"] += 1
total = sum(c.values())
for k, v in c.most_common(): print(f"{k:28} {v:6,} {v/total:5.1%}")
PY
```

Before the change it was `matched_name_department 7,328 (35.9%)`. I measured a
floor of 63.3% afterwards. If it comes back below ~60%, something is wrong and
I want to see it rather than have you work around it.

---

## Before step 4 — the RateMyProfessors question

Steps 4–6 collect from RateMyProfessors. Their terms of use prohibit automated
access and redistribution of user content, and there is no official API or
licensing route. That is a decision for you, not a technical blocker, and the
honest options are:

1. **Ask them.** Their terms say "except with our prior permission". A
   single-university student tool is the kind of request that sometimes gets a
   yes, and it is the only clean path.
2. **Link out instead of storing.** Keep the resolved profile id per instructor
   and deep-link to their page. Far weaker claim against you than holding
   review text.
3. **Lean on the public evaluations.** A&M publishes course-level evaluation
   results by statute. They do not include the four instructor-specific
   questions, so they answer "what is this class like", not "is this professor
   good".

If you go ahead, pace it. `robots.txt` publishes `Crawl-delay: 10`; the
`--rpm` flag below is what sets that.

## 4. Load the professor roster

```bash
.venv/bin/python -m app.ingest.load_rmp --school-id 1003 --detail-limit 0 --dry-run
.venv/bin/python -m app.ingest.load_rmp --school-id 1003 --detail-limit 0 --rpm 6
```

`--detail-limit 0` fetches the listing only — no comments. This is the step
worth ~1,200 extra linked instructors on its own: without it the candidate pool
is only the ~1,991 professors the pipeline already matched, not the school's
6,022.

**Check:**

```sql
select count(*) from rmp_professors;
```

Near 6,022 means the full roster loaded; ~1,991 means it did not.

## 5. Comments, for the summaries and traits

```bash
.venv/bin/python -m app.ingest.load_rmp --school-id 1003 --rpm 6
```

Resumable. `--refetch-days` controls how stale a professor must be before
re-fetching.

## 6. Summaries and traits

```bash
.venv/bin/python -m app.ingest.run_summaries --limit 5 --dry-run
.venv/bin/python -m app.ingest.run_summaries
.venv/bin/python -m app.ingest.run_traits --limit 5 --dry-run
.venv/bin/python -m app.ingest.run_traits
```

Both need `GEMINI_API_KEY`; summaries also need it set **on the Render
service**, not just locally. Without it `make_summarizer` logs a warning and
silently writes stub text. Confirm with:

```sql
select model, count(*) from summaries group by model order by 2 desc;
```

If `stub` appears, delete those rows and re-run with the key set:
`delete from summaries where model = 'stub';`

---

## Finally

```sql
-- what a student actually sees: sections with a usable timetable and a rating
select count(*) filter (where s.meets <> '[]'::jsonb) as schedulable,
       count(*) filter (where s.meets <> '[]'::jsonb and i.rmp_id is not null) as with_rating
from sections s left join instructors i on i.id = s.instructor_id
where s.term = 'SPRING 2027';
```

That ratio is the product. Send it to me with the match_status table from step
3 and I can tell you whether what is left is namesakes, professors genuinely
absent from RMP, or something we have not found yet.
