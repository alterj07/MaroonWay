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

Create the Supabase project, click **Connect** at the top of the dashboard, copy
the **Session pooler** string (port 5432 — session mode keeps the prepared
statements and session state that the transaction pooler on 6543 drops) into
`DATABASE_URL` with the `postgresql+asyncpg://` scheme, and apply the schema — either paste `sql/001_schema.sql` and `sql/002_indexes.sql`
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

The source of truth is the project's own pipeline output, on the `data` branch.
No scraping is needed: it already carries matched professors, their aggregates,
and the review text.

```bash
# Catalog: titles, credits, descriptions, prerequisites.
python -m app.ingest.load_catalog   ../Data/courses.csv              #  5,262 courses

# Grades: one row per section per term.
python -m app.ingest.load_grades    ../Data/output/sections_all.csv  # 83,926 rows

# RateMyProfessors: aggregates, review text, and professor matching.
python -m app.ingest.load_rmp_dataset ../Data/output/schedule_dataset.csv

# The full RMP roster, which is what professor coverage actually depends on.
python -m app.ingest.load_rmp --school-id 1003 --detail-limit 0

# Sections - the meeting times the scheduler needs. Until a real export exists,
# generate a demo term from real courses and instructors (invented times, and
# the term is labelled DEMO so it cannot be mistaken for the registrar's).
python -m app.ingest.make_demo_sections
python -m app.ingest.load_sections out/demo_sections.csv

# Summaries (Gemini). Read the prompts and token estimate before spending quota.
python -m app.ingest.run_summaries --limit 5 --dry-run
python -m app.ingest.run_summaries --limit 5

# Traits (Jev). What the reviews say about quizzes, exams, lecturing,
# attendance and extra credit, as typed values.
python -m app.ingest.run_traits --limit 5 --dry-run
python -m app.ingest.run_traits --limit 50
```

Every loader takes `--dry-run` (parse and report, write nothing) and `--limit`.

Before trusting a new file, profile it — read-only, and it reports which of our
fields mapped, what it could not place, and whether the file carries meeting
times:

```bash
python -m app.ingest.profile_csv ../Data/output/sections_all.csv
```

If a column does not map, add it to `OVERRIDES` in `app/ingest/columns.py` —
the only file that needs to know a CSV's header spellings.

`app/ingest/load_rmp.py` is the scraper path, now only useful for refreshing
data the pipeline has not collected (notably professors missing from its
1,985-professor roster).

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

## Scheduling

`app/services/scheduling.py`, behind `POST /schedule`. The planning doc's one
REQUIRED rule is the minimum gap between classes: **20 minutes by default,
raisable by the student**. A class that ends exactly when the next begins is a
conflict, because the student still has to walk; 19 minutes is a conflict;
exactly 20 is allowed; an online section has no meetings and cannot clash with
anything.

Schedules are ranked by the doc's rule — RMP score first, then difficulty — and
when nothing fits, the response's `detail` names the near miss ("the closest
any two of their sections come is 20 min, less than the 90 min required"), so
the UI can say which constraint to relax.

**Meeting times are the one thing no source has.** A&M closed its public course
API in 2023 and the replacement requires a student login: `compass-ssb` answers
403, the Banner 9 paths 404, and Howdy and College Scheduler redirect to auth.
So `/schedule` runs against whatever `load_sections.py` is given. Until that is
a real export, `make_demo_sections` builds a term from real courses, real
instructors and real ratings with invented times, labelled `DEMO <term>`.

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
- **`RMP_SCHOOL_ID` is 1003** (A&M College Station), confirmed from the
  pipeline's RMP cache, where `school.legacyId` is 1003 and `school.id` decodes
  to "School-1003". Galveston is 1006. The 19496 in `rmp_roster.csv` is not the
  id the API takes. Blinn College is a separate school.
- **Meeting times do not exist in any source yet**, and cannot be scraped: see
  Scheduling above. The scheduler, its tests and its loader are all in place;
  they need a sections export from an authenticated session.
- **Professor matching depends on the roster.** With only the pipeline's 1,985
  professors, 1,919 of 5,548 instructors linked. Fetching the school's full
  6,022-professor roster took that to 3,127 (56%). Matching runs with the CSV
  name as the target, since that is the side carrying "RODRIGUEZ C"; run the
  other way round, fuzzy matching attaches it to the wrong Rodriguez.

### Loading order

```bash
python -m app.ingest.apply_sql sql/001_schema.sql sql/002_indexes.sql sql/003_extra_datapoints.sql
python -m app.ingest.load_catalog      ../Data/courses.csv
python -m app.ingest.load_grades       ../Data/output/sections_all.csv
python -m app.ingest.load_rmp_dataset  ../Data/output/schedule_dataset.csv
python -m app.ingest.load_extras       ../Data/output/schedule_dataset.csv
python -m app.ingest.load_rmp --school-id 1003 --detail-limit 0
python -m app.ingest.make_demo_sections --courses 60 --per-course 6
python -m app.ingest.load_sections     out/demo_sections.csv
```

`load_extras` must run after both `load_grades` and `load_catalog`: it fills in
the campus, course level and teaching history onto rows they create.

### Real meeting times

`Data/output/schedule_cache/<termcode>.json` is one term of A&M's Banner
class-search output -- the service Howdy drives -- and it is the only file in
the project that carries **meeting times**: days, start and end, building and
room. Load it with::

    python -m app.ingest.load_schedule_json ../Data/output/schedule_cache/202711.json \
                                            ../Data/output/schedule_cache/202712.json

Term codes are `YYYYSC`: season 1 spring, 2 summer, 3 fall, then a campus digit,
1 College Station and 2 Galveston.

The CSVs themselves carry grade distributions, the catalog and RateMyProfessors
ratings, and **no meeting times at all** -- the only clock times in them are
inside review comments ("exams were at 7:30pm"). `make_demo_sections` exists for
when no schedule file is available: it invents times and labels the term
`DEMO <term>` so they cannot be mistaken for the registrar's.

## Deploying to Render

Both halves run on Render, and `render.yaml` at the repository root describes
them. In Render: **New > Blueprint**, point it at this repository, apply.

| Service | What it is | Why it is separate |
| --- | --- | --- |
| `maroonway` | the Next.js site (Node) | what a student opens |
| `maroonway-api` | this backend (Python) | what the site reads from |

The site talks to the API server-side only, so the API needs no CORS and the
browser never sees its URL or its tokens.

Render prompts for four secrets and handles the rest:

| Prompted | Value |
| --- | --- |
| `DATABASE_URL` | the Supabase **session pooler** string, scheme rewritten to `postgresql+asyncpg://` |
| `GEMINI_API_KEY` | from Google AI Studio |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | from the Google Cloud OAuth client |

`NEXTAUTH_SECRET`, `INTERNAL_TOKEN`, `ADMIN_TOKEN` and `IMPORT_TOKEN` are
generated by Render. `BACKEND_URL` and the site's copy of `INTERNAL_TOKEN` are
filled in from the API service with `fromService`, so the token cannot drift
between the two -- a mismatch there lets sign-in succeed and then silently 401s
every save, which is tedious to diagnose and easy to avoid.

One thing Render cannot do for you: add the callback to the Google Cloud
console, under Credentials > your OAuth client > Authorized redirect URIs:

    https://maroonway.onrender.com/api/auth/callback/google

Without it Google answers `redirect_uri_mismatch`. The host must match
`NEXTAUTH_URL` exactly -- the sign-in state cookie is set on that host and
Google returns to it, so a mismatch loses the cookie and every sign-in fails
with "State cookie was missing".

Nothing in the application code needs changing for any of this. The engine
already sets `statement_cache_size=0` so either Supabase pooler works, the
lifespan survives a database it cannot reach (so `/healthz` reports the problem
instead of failing the deploy), and nothing binds to localhost.

Three things to know:

- **One worker, deliberately.** A second worker holds a second, independent
  copy of the cache and halves the hit rate. Scale by moving the cache behind
  Redis, not by adding workers.
- **The free plan sleeps after 15 minutes idle.** The first request after that
  pays for a cold start plus the cache warm-up, which is why the blueprint sets
  `CACHE_WARM_COUNT=10` rather than the default 25. The sign-in gate is the one
  screen that needs no API, so a visitor arriving cold still gets a working
  page.
- **Migrations and loaders run from a laptop, not from Render.** The free plan
  has no shell, and both talk to the same Supabase database anyway, so
  `apply_sql` and the ingest commands stay where they are.

Once deployed the API is reachable by anyone who finds the URL. The `/me`
endpoints are guarded by `INTERNAL_TOKEN` and the admin ones by `ADMIN_TOKEN`,
but the course and professor reads are open. That is fine for public catalog
data; it is not a place to put anything student-specific.
