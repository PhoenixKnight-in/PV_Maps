"""Runtime configuration, from the environment only.

ARCHITECTURE.md 9.2: "Configure CORS to permit only the web application's
deployed origin." A wildcard origin is therefore not reachable from this file --
there is no value of CORS_ALLOW_ORIGINS that produces `allow_origins=["*"]`,
because the one time that would matter is a deployed environment where somebody
set it in a hurry.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

__all__ = ["Settings", "load_settings"]

_DEFAULT_ORIGINS = "http://localhost:8080,http://localhost:5173"


def _csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str | None
    """None runs the API with no database. Every roof route then answers 503
    instead of pretending -- used by tests, and by `docker compose up` before
    the seeder has run."""

    cors_allow_origins: list[str] = field(default_factory=list)
    log_level: str = "info"
    sql_echo: bool = False

    search_limit: int = 10
    """Pilot search is over one Vellore ward. A long list is a sign the query
    matched nothing specific, not a sign the user wants to scroll."""

    sizing_run_ttl_days: int = 7
    """ARCHITECTURE.md 8: the run id is short-lived. The row holds no consumer
    number, name or address, but it is still a household's consumption, so it
    expires rather than accumulating."""

    bill_upload_max_bytes: int = 8 * 1024 * 1024
    """ARCHITECTURE.md 8: "Limit bill-extraction requests by IP and size."""

    bill_extract_per_minute: int = 6

    @property
    def has_database(self) -> bool:
        return bool(self.database_url)


def load_settings(env: dict[str, str] | None = None) -> Settings:
    e = os.environ if env is None else env

    origins = _csv(e.get("CORS_ALLOW_ORIGINS", _DEFAULT_ORIGINS))
    if "*" in origins:
        raise ValueError(
            "CORS_ALLOW_ORIGINS='*' is refused. ARCHITECTURE.md 9.2 permits only "
            "the deployed web origin. List it explicitly."
        )

    return Settings(
        database_url=e.get("DATABASE_URL") or None,
        cors_allow_origins=origins,
        log_level=e.get("PVMAPS_LOG_LEVEL", "info").lower(),
        sql_echo=e.get("PVMAPS_SQL_ECHO", "").lower() in {"1", "true", "yes"},
        search_limit=int(e.get("PVMAPS_SEARCH_LIMIT", "10")),
        sizing_run_ttl_days=int(e.get("PVMAPS_SIZING_RUN_TTL_DAYS", "7")),
        bill_upload_max_bytes=int(e.get("PVMAPS_BILL_MAX_BYTES", str(8 * 1024 * 1024))),
        bill_extract_per_minute=int(e.get("PVMAPS_BILL_RATE_PER_MINUTE", "6")),
    )
