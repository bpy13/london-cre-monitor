"""Error classification, incident references and logging."""

from __future__ import annotations

import logging
import re

import pytest

from cre_monitor.errors import classify, incident_from_exception, make_incident, new_incident_id
from tests.support.samples import REAL_403


@pytest.mark.parametrize("text, code", [
    (REAL_403, "access_denied"),
    ("AuthenticationError: Error code: 401 - invalid x-api-key", "auth"),
    ("BadRequestError: Error code: 400 - Your credit balance is too low to access the Anthropic API", "credit"),
    ("RateLimitError: Error code: 429 - rate_limit_error", "rate_limit"),
    ("InternalServerError: Error code: 529 - overloaded_error", "service"),
    ("APIConnectionError: Connection error. ConnectTimeout", "network"),
    # The real 400 seen in the first live run (thinking-block signature / tool list mismatch).
    ("AnthropicInvalidRequestError: Error code: 400 - {'type': 'error', 'error': {'type': "
     "'invalid_request_error', 'message': 'messages.1.content.4: Invalid `signature` in `thinking` block.'}}",
     "app_error"),
    ("RuntimeError: LLM requested while CRE_DEMO_MODE is on", "config"),
    ("ValueError: something odd", "unknown"),
])
def test_classify(text, code):
    assert classify(text).code == code


def test_incident_id_format():
    assert re.fullmatch(r"ERR-\d{8}-\d{4}-[0-9A-F]{4}", new_incident_id())


def test_make_incident_logs_traceable_record(caplog):
    assert make_incident([], total=True) is None
    with caplog.at_level(logging.ERROR, logger="cre_monitor.errors"):
        inc = make_incident(
            [("office-rents", "ValueError: odd"), ("macro-economy", REAL_403)],
            total=False, thread_id="t1", run_id="r1",
        )
    assert inc.category.code == "access_denied"          # most actionable known category wins
    assert inc.scope == "partial" and inc.affected == ["office-rents", "macro-economy"]
    record = caplog.text
    assert inc.id in record and "thread=t1" in record and "Request not allowed" in record


def test_incident_from_exception_is_total():
    inc = incident_from_exception(ConnectionError("Connection refused"), step="chat", thread_id="t9")
    assert inc.scope == "total" and inc.category.code == "network" and inc.thread_id == "t9"
