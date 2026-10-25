"""A normalisation layer over ``RateMyProfessor-Database-APIs`` 1.1.1.

Everything below was read off the installed package, not its PyPI blurb, which
documents neither the return types nor the costs.

What it exposes:

* ``fetch_all_professors_from_a_school(school_id)`` -- paginates the whole school
  (4-5k professors) and returns ``Professor_Gist`` objects: legacy_id, the
  base64 GraphQL node id, names, department, school, avg_rating, avg_difficulty,
  num_ratings, would_take_again_percent. No comments.
* ``fetch_a_professor(legacy_id)`` -- returns a ``Professor`` with per-review
  dicts. **It costs two HTTP requests**: it first downloads the professor's HTML
  page and regexes ``window.__RELAY_STORE__`` out of it just to translate the
  numeric id into the node id, then runs the GraphQL query. (That translation
  also raises ``NameError`` instead of its intended ``ValueError`` when it
  fails.) Since the school listing already gives us the node id, we skip that
  half -- see :func:`fetch_professor_by_node_id`, which reuses the package's own
  query string and parser over a single request.
* ``fetch_a_school(school_id)`` -- school-level ratings; unused here.

Per-review fields really available: ``comment``, ``date``, ``class``,
``helpfulRating``, ``clarityRating``, ``difficultyRating``,
``attendanceMandatory``, ``isForOnlineClass``, ``textbookUse``, ``isForCredit``,
``flagStatus``, ``createdByUser``. Two of those answer planning-doc wants
directly: attendance and web-vs-F2F. Two wants are *not* in here -- letter
grades and extra credit -- so grades come from the CSV and extra credit, if it
ever appears, comes out of the comment text via the summariser.

Would-take-again is professor-level only (and ``-1`` means nobody answered), so
it can weight a professor but never a single class.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

GRAPHQL_ENDPOINT = "https://www.ratemyprofessors.com/graphql"
#: The package sends this Basic header; it is a literal "test:test" in its source.
DEFAULT_TIMEOUT = 20.0

_FIELD_RE = re.compile(r"[^a-z0-9]+")
_NODE_ID_RE = re.compile(r"^[A-Za-z]+-(\d+)$")


def _norm_field(name: str) -> str:
    return _FIELD_RE.sub("", name.lower())


def _flatten(raw: Any) -> dict[str, Any]:
    """Field name (normalised) -> value, for a dict or an object alike."""
    if isinstance(raw, dict):
        return {_norm_field(str(key)): value for key, value in raw.items()}
    flat: dict[str, Any] = {}
    for attr in dir(raw):
        if attr.startswith("_"):
            continue
        try:
            value = getattr(raw, attr)
        except Exception:  # noqa: BLE001 - scraper objects do odd things
            continue
        if callable(value):
            continue
        flat[_norm_field(attr)] = value
    return flat


def _pick(raw: Any, *aliases: str, default: Any = None) -> Any:
    """Read a field by any of its spellings, **in the order given**.

    Order matters: a ``Professor`` has both ``legacy_id`` (the numeric id the
    site's URLs use) and ``id`` (a base64 GraphQL node id), and asking for "id"
    first would hand back something that is not a number.
    """
    flat = _flatten(raw)
    for alias in aliases:
        key = _norm_field(alias)
        if key in flat:
            return flat[key]
    return default


def to_jsonable(raw: Any) -> Any:
    """Make a scraper payload safe for a JSONB column."""
    if raw is None or isinstance(raw, (str, int, float, bool)):
        return raw
    if isinstance(raw, dict):
        return {str(k): to_jsonable(v) for k, v in raw.items()}
    if isinstance(raw, (list, tuple, set)):
        return [to_jsonable(v) for v in raw]
    if isinstance(raw, datetime):
        return raw.isoformat()
    if hasattr(raw, "__dict__"):
        return {k: to_jsonable(v) for k, v in vars(raw).items() if not k.startswith("_")}
    return str(raw)


def _as_dict(raw: Any) -> dict[str, Any]:
    value = to_jsonable(raw)
    return value if isinstance(value, dict) else {"value": value}


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return int(number) if number is not None else None


def _as_bool(value: Any) -> bool | None:
    """RMP sends these as "mandatory"/"non mandatory"/"" as often as booleans."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1", "mandatory"}:
        return True
    if text in {"false", "no", "n", "0", "non mandatory", "not mandatory"}:
        return False
    return None


def decode_node_id(node_id: Any) -> int | None:
    """``"VGVhY2hlci0yMDAxNDc="`` -> ``200147``.

    GraphQL node ids are base64 of ``Teacher-<legacyId>``, so a numeric id can be
    recovered without another request.
    """
    if node_id is None:
        return None
    text = str(node_id)
    try:
        decoded = base64.b64decode(text + "=" * (-len(text) % 4)).decode("utf-8", "ignore")
    except (binascii.Error, ValueError):
        return None
    match = _NODE_ID_RE.match(decoded.strip())
    return int(match.group(1)) if match else None


def parse_rmp_date(value: Any) -> datetime | None:
    """Parse the scraper's date formats.

    Its reviews carry Go's default stamp -- ``2012-01-02 00:35:24 +0000 UTC`` --
    but ISO strings and epoch seconds turn up too.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)

    text = re.sub(r"\s+(UTC|GMT)$", "", str(value).strip())
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    try:
        from dateutil import parser as date_parser

        parsed = date_parser.parse(text)
    except Exception:  # noqa: BLE001 - an unparseable date is data, not a crash
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(slots=True)
class RatingRecord:
    rmp_id: int
    class_code: str | None
    comment: str | None
    helpful: float | None
    clarity: float | None
    difficulty: float | None
    rated_at: datetime | None
    is_online: bool | None = None
    attendance_mandatory: bool | None = None
    textbook_use: str | None = None
    is_for_credit: bool | None = None
    #: RateMyProfessors' own id for the review, when the source provides it.
    #: Makes upserts exact rather than heuristic.
    rating_id: int | None = None
    #: The three fields the pinned package's parser drops. They are present in
    #: the richer payload the project's own scraper collected, and two of them
    #: answer planning-doc requirements directly: the student's letter grade and
    #: their individual would-take-again answer.
    grade: str | None = None
    would_take_again: bool | None = None
    rating_tags: str | None = None
    thumbs_up: int | None = None
    thumbs_down: int | None = None
    course_match_status: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProfessorRecord:
    rmp_id: int
    node_id: str | None
    first_name: str | None
    last_name: str | None
    department: str | None
    school_id: str | None
    avg_rating: float | None
    avg_difficulty: float | None
    num_ratings: int
    would_take_again_percent: float | None
    ratings_distribution: dict[str, Any] | None
    course_codes: list[dict[str, Any]] | None = None
    ratings: list[RatingRecord] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p).strip()


def normalize_rating(raw: Any, rmp_id: int) -> RatingRecord:
    class_code = _pick(raw, "class", "className", "course")
    textbook = _pick(raw, "textbookUse", "textbook_use")
    return RatingRecord(
        rmp_id=rmp_id,
        class_code=(
            re.sub(r"[^A-Z0-9]", "", str(class_code).upper()) or None if class_code else None
        ),
        comment=(str(c).strip() or None if (c := _pick(raw, "comment", "rComments")) else None),
        helpful=_as_float(_pick(raw, "helpfulRating", "helpful", "rHelpful")),
        clarity=_as_float(_pick(raw, "clarityRating", "clarity", "rClarity")),
        difficulty=_as_float(_pick(raw, "difficultyRating", "difficulty", "rEasy")),
        rated_at=parse_rmp_date(_pick(raw, "date", "rDate", "createdAt")),
        is_online=_as_bool(_pick(raw, "isForOnlineClass", "is_for_online_class", "onlineClass")),
        attendance_mandatory=_as_bool(
            _pick(raw, "attendanceMandatory", "attendance_mandatory", "attendance")
        ),
        textbook_use=str(textbook) if textbook not in (None, "") else None,
        is_for_credit=_as_bool(_pick(raw, "isForCredit", "is_for_credit")),
        rating_id=_as_int(_pick(raw, "legacyId", "legacy_id", "ratingId")),
        grade=(str(g).strip() or None if (g := _pick(raw, "grade")) else None),
        would_take_again=_as_bool(_pick(raw, "wouldTakeAgain", "would_take_again")),
        rating_tags=(str(t).strip() or None if (t := _pick(raw, "ratingTags")) else None),
        thumbs_up=_as_int(_pick(raw, "thumbsUpTotal", "thumbs_up")),
        thumbs_down=_as_int(_pick(raw, "thumbsDownTotal", "thumbs_down")),
        course_match_status=(
            str(s).strip() or None if (s := _pick(raw, "course_match_status")) else None
        ),
        raw=_as_dict(raw),
    )


def normalize_professor(raw: Any) -> ProfessorRecord | None:
    """One scraper payload (``Professor`` or ``Professor_Gist``) to a record.

    ``None`` when no numeric id can be recovered, which is the only case where
    the row would be unusable.
    """
    node_id = _pick(raw, "id", "nodeId")
    rmp_id = _as_int(_pick(raw, "legacyId", "legacy_id", "rmpId", "professorId", "tid"))
    if rmp_id is None:
        rmp_id = _as_int(node_id) or decode_node_id(node_id)
    if rmp_id is None:
        return None

    num_ratings = _as_int(_pick(raw, "numRatings", "numberOfRatings")) or 0
    avg_rating = _as_float(_pick(raw, "avgRating", "averageRating"))
    avg_difficulty = _as_float(_pick(raw, "avgDifficulty", "averageDifficulty"))
    if num_ratings == 0:
        # The listing reports 0.0 for unrated professors; that is "no data", not
        # "rated zero", and feeding it to the scoring prior would be a lie.
        avg_rating = None if not avg_rating else avg_rating
        avg_difficulty = None if not avg_difficulty else avg_difficulty

    wta = _as_float(_pick(raw, "wouldTakeAgainPercent", "would_take_again_percent"))
    if wta is not None and wta < 0:
        wta = None  # -1 means nobody answered

    school = _pick(raw, "school")
    school_id = None
    if isinstance(school, dict):
        school_id = school.get("legacyId") or school.get("id")
    elif school is not None:
        school_id = _pick(school, "legacyId", "id")

    raw_ratings = _pick(raw, "ratings", "reviews", default=[]) or []
    if isinstance(raw_ratings, dict):  # {"edges": [{"node": {...}}]}
        raw_ratings = _pick(raw_ratings, "edges", "nodes", "items", default=[]) or []
    ratings = []
    for entry in raw_ratings:
        node = entry["node"] if isinstance(entry, dict) and "node" in entry else entry
        ratings.append(normalize_rating(node, rmp_id))

    distribution = to_jsonable(_pick(raw, "ratingsDistribution", "ratings_distribution"))
    course_codes = to_jsonable(_pick(raw, "courseCodes", "course_codes"))

    return ProfessorRecord(
        rmp_id=rmp_id,
        node_id=str(node_id) if node_id is not None else None,
        first_name=(str(v).strip() if (v := _pick(raw, "firstName", "first_name")) else None),
        last_name=(str(v).strip() if (v := _pick(raw, "lastName", "last_name")) else None),
        department=(str(v).strip() if (v := _pick(raw, "department", "departmentName")) else None),
        school_id=str(school_id) if school_id is not None else None,
        avg_rating=avg_rating,
        avg_difficulty=avg_difficulty,
        num_ratings=num_ratings,
        would_take_again_percent=wta,
        ratings_distribution=distribution if isinstance(distribution, dict) else None,
        course_codes=course_codes if isinstance(course_codes, list) else None,
        ratings=ratings,
        raw=_as_dict(raw),
    )


# --- talking to RateMyProfessors ----------------------------------------------


def _api() -> Any:
    """Imported lazily, so the API server runs without the scraper installed."""
    import RateMyProfessor_Database_APIs as rmp_api

    return rmp_api


def _graphql_bits() -> tuple[str, dict[str, str]]:
    """The package's own query string and headers, so we inherit its schema."""
    from RateMyProfessor_Database_APIs import helper_queries, main as rmp_main

    return helper_queries.fetch_a_professors_query_string, dict(rmp_main.HEADERS)


async def fetch_school(school_id: str) -> Any:
    return await asyncio.to_thread(_api().fetch_a_school, school_id)


async def fetch_all_professors(school_id: str) -> list[ProfessorRecord]:
    """Every professor at a school, aggregates only.

    One paginated crawl (500 per page, with a tqdm bar on stderr). Cheap enough
    to run whole; the per-professor comment fetch is what needs rationing.
    """
    raw = await asyncio.to_thread(_api().fetch_all_professors_from_a_school, school_id)
    records = (normalize_professor(entry) for entry in (raw or []))
    return [record for record in records if record is not None]


async def fetch_professor_by_node_id(
    node_id: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> ProfessorRecord | None:
    """One professor's full ratings in a single request.

    Uses the package's query string and ``parse_professor``, but supplies the
    node id we already hold instead of letting it re-derive one by scraping an
    HTML page. That halves the requests and drops the package's flakiest step.
    """
    from RateMyProfessor_Database_APIs import helper_classes

    query, headers = _graphql_bits()
    headers["Referer"] = "https://www.ratemyprofessors.com/professor/"
    payload = {"query": query, "variables": {"id": node_id}}

    owned = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        response = await http.post(GRAPHQL_ENDPOINT, json=payload, headers=headers)
        response.raise_for_status()
        body = response.json()
    finally:
        if owned:
            await http.aclose()

    if not body.get("data", {}).get("node"):
        return None
    return normalize_professor(helper_classes.parse_professor(body))


async def fetch_professor(legacy_id: int | str) -> ProfessorRecord | None:
    """Fallback for when only the numeric id is known.

    Goes through the package's public function, which means an HTML scrape plus
    the GraphQL call. Prefer :func:`fetch_professor_by_node_id`.
    """
    raw = await asyncio.to_thread(_api().fetch_a_professor, legacy_id)
    return normalize_professor(raw) if raw is not None else None
