"""DATABASE_URL: accept what people paste, refuse what cannot work."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


class TestDatabaseUrl:
    @pytest.mark.parametrize(
        "given",
        [
            "postgresql://user:pw@host:5432/postgres",
            "postgres://user:pw@host:5432/postgres",
        ],
    )
    def test_a_psql_style_url_is_given_the_async_driver(self, given: str) -> None:
        """Every tool but this one prints postgresql://, so rewrite rather than
        refuse: demanding the +asyncpg suffix by hand is a trap with no upside,
        and without it SQLAlchemy loads the synchronous driver and the app dies.
        """
        assert Settings(database_url=given).database_url.startswith("postgresql+asyncpg://")
        assert Settings(database_url=given).database_url.endswith("@host:5432/postgres")

    def test_an_async_url_is_left_alone(self) -> None:
        url = "postgresql+asyncpg://user:pw@host:5432/postgres"
        assert Settings(database_url=url).database_url == url

    def test_a_project_url_names_the_confusion(self) -> None:
        """Supabase offers several strings and only one is a connection. This
        one reached SQLAlchemy as a dialect name and died with "Can't load
        plugin: sqlalchemy.dialects:https"."""
        with pytest.raises(ValidationError) as caught:
            Settings(database_url="https://abcdefgh.supabase.co")
        message = str(caught.value)
        assert "project URL" in message
        assert "Session pooler" in message

    @pytest.mark.parametrize("given", ["", "   ", "abcdefgh.supabase.co", "mysql://u:p@h/db"])
    def test_anything_that_is_not_postgres_is_refused(self, given: str) -> None:
        with pytest.raises(ValidationError):
            Settings(database_url=given)
