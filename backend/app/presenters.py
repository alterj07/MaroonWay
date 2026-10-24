"""Turn repository rows into the API's nested payloads.

Also where the weighted composite is applied: the SQL views hand back shrunk
values, settings hold the weights, and these functions put the two together.
"""

from __future__ import annotations

from typing import Any

from app.scoring import ScoreWeights, composite_from_adjusted

SCORE_FIELDS = (
    "rating_count",
    "raw_rating",
    "raw_difficulty",
    "would_take_again_percent",
    "adj_rating",
    "adj_difficulty",
    "adj_would_take_again",
    "adj_gpa",
)


def _number(value: Any) -> float | None:
    return None if value is None else float(value)


def _composite(row: dict[str, Any], weights: ScoreWeights) -> float:
    return composite_from_adjusted(
        adj_rating=float(row["adj_rating"]),
        adj_difficulty=float(row["adj_difficulty"]),
        adj_would_take_again=_number(row.get("adj_would_take_again")),
        adj_gpa=_number(row.get("adj_gpa")),
        weights=weights,
    )


def score_block(row: dict[str, Any], weights: ScoreWeights) -> dict[str, Any]:
    block = {field: _number(row.get(field)) for field in SCORE_FIELDS}
    block["rating_count"] = int(row.get("rating_count") or 0)
    block["composite"] = _composite(row, weights)
    return block


def course_score(row: dict[str, Any], weights: ScoreWeights) -> dict[str, Any]:
    return {
        "course_id": int(row["course_id"]),
        "code": row["code"],
        "title": row.get("title"),
        "campus": row.get("campus"),
        "honors": bool(row.get("honors")),
        "class_rating_count": int(row.get("class_rating_count") or 0),
        "section_count": int(row.get("section_count") or 0),
        "adj_rating": float(row["adj_rating"]),
        "adj_difficulty": float(row["adj_difficulty"]),
        "adj_would_take_again": _number(row.get("adj_would_take_again")),
        "adj_gpa": _number(row.get("adj_gpa")),
        "composite": _composite(row, weights),
    }


def course_instructor(row: dict[str, Any], weights: ScoreWeights) -> dict[str, Any]:
    payload = {
        "instructor_id": int(row["instructor_id"]),
        "full_name": row["full_name"],
        "department": row.get("department"),
        "rmp_id": row.get("rmp_id"),
        "class_rating_count": int(row.get("class_rating_count") or 0),
        "instructor_rating_count": int(row.get("instructor_rating_count") or 0),
        "section_count": int(row.get("section_count") or 0),
        "adj_rating": float(row["adj_rating"]),
        "adj_difficulty": float(row["adj_difficulty"]),
        "adj_would_take_again": _number(row.get("adj_would_take_again")),
        "adj_gpa": _number(row.get("adj_gpa")),
    }
    payload["composite"] = _composite(row, weights)
    return payload


def search_hit(row: dict[str, Any], weights: ScoreWeights) -> dict[str, Any]:
    return {
        "instructor_id": int(row["instructor_id"]),
        "full_name": row["full_name"],
        "department": row.get("department"),
        "rmp_id": row.get("rmp_id"),
        "name_similarity": _number(row.get("name_similarity")),
        "score": score_block(row, weights),
    }


def professor_payload(raw: dict[str, Any], weights: ScoreWeights) -> dict[str, Any]:
    """The professor detail payload -- this is the object that gets cached."""
    return {
        "instructor_id": int(raw["instructor_id"]),
        "full_name": raw["full_name"],
        "department": raw.get("department"),
        "rmp_id": raw.get("rmp_id"),
        "score": score_block(raw, weights),
        "courses": [course_score(row, weights) for row in raw.get("courses", [])],
        "grades": [
            {
                "code": row["code"],
                "title": row.get("title"),
                "term": row["term"],
                "term_year": row.get("term_year"),
                "term_season": row.get("term_season"),
                "section": row.get("section"),
                "gpa": _number(row.get("gpa")),
                "enrolled": row.get("enrolled"),
            }
            for row in raw.get("grades", [])
        ],
        "recent_comments": [
            {
                "class_code": row.get("class_code"),
                "comment": row["comment"],
                "helpful": _number(row.get("helpful")),
                "clarity": _number(row.get("clarity")),
                "difficulty": _number(row.get("difficulty")),
                "rated_at": row.get("rated_at"),
            }
            for row in raw.get("recent_comments", [])
        ],
        "summaries": [dict(row) for row in raw.get("summaries", [])],
    }
