"""User-facing error handling: classify failures and raise traceable incidents.

When something goes wrong (most often the Claude API: wrong key, no access,
no credit, rate limits), business users should see a clear explanation and a
**reference ID** they can send to the engineering team - not a stack of raw
exception text. Engineers, in turn, need the full technical detail.

This module does both:

* :func:`classify` maps raw error text to an :class:`ErrorCategory` with a
  plain-English title, explanation and suggested actions.
* :func:`make_incident` bundles all failures of one run into an
  :class:`Incident` with a unique ID (``ERR-YYYYMMDD-HHMM-XXXX``) and logs the
  full technical details under that ID, so an engineer can find them with
  ``grep ERR-...`` in ``data/logs/``.

The UI and CLI render incidents; reports keep their own data-quality notes.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from cre_monitor.config import get_settings

logger = logging.getLogger(__name__)


class ErrorCategory(BaseModel):
    """How a class of failure is explained to users."""

    code: str
    title: str
    message: str
    actions: list[str]
    retryable: bool = False


#: Ordered rules: the first pattern that matches the error text wins, so more
#: specific patterns (e.g. credit balance, which is a 400) come first.
_RULES: list[tuple[str, ErrorCategory]] = [
    (r"credit balance|billing|insufficient.?credit|purchase credits", ErrorCategory(
        code="credit",
        title="AI usage credit has run out",
        message="The AI service account has no remaining credit, so the research could not run.",
        actions=["Ask the engineering team to top up the API credit.",
                 "You can still browse past briefs and the Dashboard."],
    )),
    (r"\b401\b|authentication|invalid.{0,10}(x-api-key|api.?key)|unauthori[sz]ed", ErrorCategory(
        code="auth",
        title="The AI service key was not accepted",
        message="The API key configured for this app is missing, invalid or revoked.",
        actions=["Ask the engineering team to check the ANTHROPIC_API_KEY setting.",
                 "Demo mode (Settings) still works without a key."],
    )),
    (r"\b403\b|forbidden|request not allowed|permission.?denied", ErrorCategory(
        code="access_denied",
        title="The AI service refused the request",
        message=("Access to the AI service was denied. This usually means the service is not "
                 "available for this account or from the network location the app runs in."),
        actions=["Contact the engineering team with the reference below - this needs a configuration fix.",
                 "Demo mode (Settings) and past briefs are still available."],
    )),
    (r"\b429\b|rate.?limit|too many requests", ErrorCategory(
        code="rate_limit",
        title="The AI service is busy (rate limit)",
        message="Too many requests were sent in a short time.",
        actions=["Wait a minute and ask again.",
                 "If it keeps happening, contact the engineering team with the reference below."],
        retryable=True,
    )),
    (r"\b529\b|overloaded|\b5\d\d\b|internal server error|service unavailable|bad gateway", ErrorCategory(
        code="service",
        title="The AI service is temporarily unavailable",
        message="The AI provider reported a temporary problem on their side.",
        actions=["Try again in a few minutes.",
                 "If it persists, contact the engineering team with the reference below."],
        retryable=True,
    )),
    (r"connect|timed? ?out|timeout|network|name resolution|ssl|getaddrinfo", ErrorCategory(
        code="network",
        title="Could not reach the AI service",
        message="The app could not connect to the AI service (network or firewall issue).",
        actions=["Check the internet connection / VPN and try again.",
                 "If it persists, contact the engineering team with the reference below."],
        retryable=True,
    )),
    (r"CRE_DEMO_MODE|ANTHROPIC_API_KEY", ErrorCategory(
        code="config",
        title="The app is not configured for live AI research",
        message="The AI service is not configured for this installation.",
        actions=["Ask the engineering team to configure the API key, or use demo mode."],
    )),
]

UNKNOWN = ErrorCategory(
    code="unknown",
    title="Something went wrong",
    message="An unexpected error stopped part of the research.",
    actions=["Try again.", "If it happens again, contact the engineering team with the reference below."],
    retryable=True,
)


def classify(error_text: str) -> ErrorCategory:
    """Map raw error text (e.g. ``"AnthropicPermissionDeniedError: Error code: 403 ..."``) to a category."""
    for pattern, category in _RULES:
        if re.search(pattern, error_text, flags=re.I):
            return category
    return UNKNOWN


class Incident(BaseModel):
    """All failures of one chat turn or brief, under one traceable reference."""

    id: str = Field(description="Reference users quote to engineers, e.g. ERR-20261008-1530-7F3A.")
    created_at: datetime
    category: ErrorCategory
    scope: str = Field(description="'total' (no usable answer) or 'partial' (answer may be incomplete).")
    affected: list[str] = Field(description="Steps that failed, e.g. ['office-rents', 'answer'].")
    details: list[str] = Field(description="Raw technical error messages (for engineers).")
    thread_id: str | None = None
    run_id: str | None = None
    log_file: str | None = None


def new_incident_id(now: datetime | None = None) -> str:
    """Short, sortable, unique reference: ``ERR-YYYYMMDD-HHMM-XXXX``."""
    now = now or datetime.now()
    return f"ERR-{now:%Y%m%d-%H%M}-{uuid.uuid4().hex[:4].upper()}"


def _current_log_file() -> str | None:
    """Path of the file handler's log, if logging to a file is configured."""
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler):
            return handler.baseFilename
    return None


def make_incident(
    failures: list[tuple[str, str]],
    *,
    total: bool,
    thread_id: str | None = None,
    run_id: str | None = None,
) -> Incident | None:
    """Create and log an incident for a run's failures (``None`` if there were none).

    Args:
        failures: ``(step, raw error text)`` pairs, e.g. ``("office-rents", "...403...")``.
        total: True if the run produced no usable result.
        thread_id: Chat conversation id, if any.
        run_id: Graph run id, if any.
    """
    if not failures:
        return None
    # The most actionable category wins (rules are ordered); fall back to the first error.
    categories = [classify(text) for _, text in failures]
    known = [c for c in categories if c.code != "unknown"]
    category = known[0] if known else categories[0]
    incident = Incident(
        id=new_incident_id(), created_at=datetime.now(), category=category,
        scope="total" if total else "partial",
        affected=list(dict.fromkeys(step for step, _ in failures)),
        details=[f"{step}: {text}" for step, text in failures],
        thread_id=thread_id, run_id=run_id, log_file=_current_log_file(),
    )
    # One searchable log record with everything an engineer needs.
    logger.error(
        "Incident %s | category=%s scope=%s thread=%s run=%s demo=%s offline=%s\n%s",
        incident.id, category.code, incident.scope, thread_id, run_id,
        get_settings().cre_demo_mode, get_settings().cre_offline,
        "\n".join(f"  - {d}" for d in incident.details),
    )
    return incident


def incident_from_exception(exc: BaseException, *, step: str, thread_id: str | None = None) -> Incident:
    """Incident for an unexpected exception that aborted a whole operation (logs the traceback)."""
    logger.exception("Unhandled error in %s (thread=%s)", step, thread_id)
    incident = make_incident([(step, f"{type(exc).__name__}: {exc}")], total=True, thread_id=thread_id)
    assert incident is not None  # non-empty failures always yield an incident
    return incident
