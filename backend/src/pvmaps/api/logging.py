"""Structured logging that cannot leak a household's identity.

ARCHITECTURE.md 8: "Do not log consumer numbers, names, addresses, bill images,
or raw OCR output."

The hard part is not our own log calls -- it is uvicorn's access log, which
prints the full request line. `GET /v1/search?q=12+Katpadi+Road` puts a user's
address into stdout, and from there into whatever ships container logs. So the
access logger is silenced here and replaced with a middleware that logs the
path with its query string removed.

That is also why `scrub()` exists and why the bill-extract route logs a byte
count and a verdict but never a field value.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Awaitable, Callable

import structlog
from starlette.requests import Request
from starlette.responses import Response
from structlog.typing import EventDict, WrappedLogger

__all__ = ["access_log_middleware", "configure_logging", "scrub"]

_SENSITIVE = {
    "q",
    "address",
    "display_name",
    "normalized_address",
    "consumer_number",
    "csn",
    "service_number",
    "name",
    "text",
    "ocr",
    "ocr_text",
    "file",
    "filename",
}


def scrub(event: EventDict) -> EventDict:
    """Drop anything whose key names a field we have promised not to log."""
    return {
        k: ("<redacted>" if k.lower() in _SENSITIVE else v)
        for k, v in event.items()
    }


def _scrub_processor(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    return scrub(event_dict)


def configure_logging(level: str = "info") -> None:
    numeric = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=numeric)

    # The whole point of this module. uvicorn's access log would print
    # `?q=<someone's address>`; ours prints the path only.
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            _scrub_processor,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


async def access_log_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """One line per request, with the query string deliberately absent.

    `request.url.path` excludes the query; `request.url` would include it. That
    difference is the whole reason this function is not uvicorn's access log.
    """
    started = time.perf_counter()
    response = await call_next(request)
    structlog.get_logger("pvmaps.access").info(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return response
