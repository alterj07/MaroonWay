# MaroonWay backend

FastAPI service behind the Next.js app: professor ratings, A&M grade history,
AI summaries of student comments, and a **server-side hot cache for recently
viewed professors**.

```
app/
  main.py          the app, lifespan, cache warm-up
  config.py        settings (env / .env)
  db.py            async engine + session
  cache.py         the hot cache          <- the interesting file
  scoring.py       the ranking formula    <- mirrors sql/002_indexes.sql
  repository.py    every SQL query the API runs
  presenters.py    rows -> API payloads (applies the score weights)
  routers/         professors, courses, meta
  services/        rmp (scraper), summarize (Gemini), names, terms, throttle
  ingest/          profile_csv, columns, load_grades, load_rmp, run_summaries, apply_sql
sql/               001_schema.sql, 002_indexes.sql (indexes + scoring views)
tests/             136 tests; the DB ones skip unless TEST_DATABASE_URL is set
```

## Setup

```bash
cd backend
uv venv --python 3.13 && uv pip install -e ".[dev]"   # or: python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env                                   # then fill in DATABASE_URL
```

Create the Supabase project, copy the **session pooler** connection string
(port 6543) into `DATABASE_URL` with the `postgresql+asyncpg://` scheme, and
apply the schema — either paste `sql/001_schema.sql` and `sql/002_indexes.sql`
into the Supabase SQL editor, or:

```bash
.venv/bin/python -m app.ingest.apply_sql sql/001_schema.sql sql/002_indexes.sql
```

Run it:

```bash
.venv/bin/python -m uvicorn app.main:app --reload --workers 1   # one worker, see below
curl -s localhost:8000/healthz
```

Interactive docs are at `/docs`.

## Loading data

```bash
# 1. Look at the CSV before trusting any mapping (read-only).
python -m app.ingest.profile_csv /path/to/grades.csv

# 2. Load it. --dry-run parses and reports without writing.
python -m app.ingest.load_grades /path/to/grades.csv --dry-run
python -m app.ingest.load_grades /path/to/grades.csv

# 3. RateMyProfessors: listing is cheap, comments are not. Smoke first.
python -m app.ingest.load_rmp --dry-run
python -m app.ingest.load_rmp --detail-limit 20

# 4. Summaries. Read the prompts and the token estimate before spending quota.
python -m app.ingest.run_summaries --limit 5 --dry-run
python -m app.ingest.run_summaries --limit 5
```

If a column does not map in step 1, add it to `OVERRIDES` in
`app/ingest/columns.py` — that is the only file that needs to know the CSV's
header spellings.

Every ingest job bumps `data_version`, which is part of every cache key, so a
running server picks up new data within 30 seconds without a restart.

## The hot cache

`app/cache.py`. Two caches (professor payloads, search results) plus a
recently-viewed log, with:

- **LRU eviction, so recency is the policy.** Every hit moves its key to the
  end; what gets evicted is always the least recently *viewed* professor.
- **Single flight.** Twenty simultaneous requests for one cold professor do one
  database round trip, not twenty.
- **Negative caching.** A missing id is remembered briefly, so a crawler hitting
  `/professors/999999` cannot re-query Postgres every time.
- **Version-namespaced keys.** `v{data_version}:prof:7` — an ingest run
  invalidates everything in one step, with no sweep and no half-old blend.
- **Warm-up at boot.** The most-rated professors are pre-loaded, so the first
  click of a demo is a HIT.

Watch it work:

```bash
curl -si localhost:8000/professors/1 | grep -i x-cache   # MISS
curl -si localhost:8000/professors/1 | grep -i x-cache   # HIT
curl -s  localhost:8000/cache/stats
```

**Run one uvicorn worker.** The cache lives in process memory, so two workers
means two independent caches and roughly half the hit rate — still correct, just
slower. Moving to Redis later means reimplementing `TTLCache` behind the same
methods; no router changes.

## Scoring

`app/scoring.py` and the `instructor_scores` / `instructor_course_scores` views.
Averages are shrunk toward the global mean in proportion to how little evidence
backs them, so 4.9-from-2-reviews ranks below 4.6-from-80. Ranking is the
product rule: **rating descending, then difficulty ascending**. The weighted
composite is a separate field, applied in Python from settings, so changing the
weights does not mean changing SQL.

The shrinkage lives in SQL (it needs database-wide aggregates) and is mirrored
by pure functions in `scoring.py` that the tests check. **Change one, change
both** — `tests/test_integration_db.py::test_the_view_and_app_scoring_agree`
fails if they drift.

## Tests

```bash
.venv/bin/python -m pytest -q                       # unit tests, no network, no DB

podman run -d --rm --name maroonway-pg -e POSTGRES_PASSWORD=maroonway \
  -e POSTGRES_DB=maroonway -p 55432:5432 docker.io/library/postgres:17-alpine
TEST_DATABASE_URL=postgresql+asyncpg://postgres:maroonway@127.0.0.1:55432/maroonway \
  .venv/bin/python -m pytest -q                     # + the SQL views
```

The database fixture drops and recreates the `public` schema. Point it at a
scratch database, **never at Supabase**.

## Notes on the upstreams

- **The RMP package is a scraper.** `RateMyProfessor-Database-APIs` is pinned at
  1.1.1 and wrapped by `app/services/rmp.py`, which keeps the untouched payload
  in a JSONB `raw` column. Its public `fetch_a_professor` costs two HTTP requests
  (it downloads the professor's HTML page just to translate the numeric id into a
  GraphQL node id); since the school listing already gives us that node id, we
  use its query string and parser directly and skip the scrape. Check A&M's terms
  before crawling the whole school.
- **Would-take-again is professor-level only**, and `-1` means nobody answered.
  Both the loader and the views refuse to treat it as a percentage.
- **Letter grades and extra credit are not in the RMP payload** — grades come
  from the CSV, and extra credit, if it shows up at all, comes out of comment
  text via the summariser.
- **Gemini's free tier is Flash / Flash-Lite** (Pro went paid in April 2026) at
  roughly 10-30 requests per minute, so summaries are a resumable batch job with
  a token bucket and backoff, never an in-request call. `GEMINI_MODEL` is an env
  var because those model names keep moving.
- **`RMP_SCHOOL_ID` must be verified by hand.** Open Texas A&M on
  ratemyprofessors.com and read the number after `/school/`. Blinn is separate.
