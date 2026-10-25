"""The loader for the datapoints the grade reports do not carry."""

from __future__ import annotations

import pytest

from app.ingest.load_catalog import _credits
from app.ingest.load_extras import _terms


class TestTeachingTerms:
    """grade_terms_json records which terms an instructor taught a course."""

    def test_reads_a_json_list(self) -> None:
        assert _terms('["FALL 2023", "FALL 2024", "SPRING 2025"]') == [
            "FALL 2023",
            "FALL 2024",
            "SPRING 2025",
        ]

    def test_trims_and_drops_blanks(self) -> None:
        assert _terms('["  FALL 2023  ", "", "   "]') == ["FALL 2023"]

    @pytest.mark.parametrize("value", ["", "   ", None, "not json", "{}", "[]", "7"])
    def test_anything_else_is_no_terms(self, value: str | None) -> None:
        """A malformed cell must not abort a 20,000-row load."""
        assert _terms(value) == []


class TestCatalogCredits:
    """Every credits cell in courses.csv ends in a full stop."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("3.", "3"),
            ("1 to 4.", "1 to 4"),
            ("0.", "0"),
            ("3", "3"),
            ("", None),
            (None, None),
        ],
    )
    def test_trailing_stop_is_dropped(self, value: str | None, expected: str | None) -> None:
        assert _credits(value) == expected
