"""LLM factory: request shape and HTTP client injection (no network).

Uses an httpx2 ``MockTransport`` inside an injected ``anthropic.DefaultHttpxClient``
to capture the exact request ChatAnthropic sends and return a canned response.
"""

from __future__ import annotations

import json

import anthropic
import httpx2
import pytest
from langchain_core.messages import HumanMessage

from cre_monitor.config import get_settings
from cre_monitor.llm import build_http_clients, get_llm

CANNED = {
    "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
    "content": [{"type": "text", "text": "OK"}], "stop_reason": "end_turn", "stop_sequence": None,
    "usage": {"input_tokens": 5, "output_tokens": 1},
}


@pytest.fixture
def live_settings(monkeypatch):
    monkeypatch.setenv("CRE_DEMO_MODE", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    get_settings.cache_clear()


def test_injected_http_client_is_used_and_request_is_valid(live_settings):
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=CANNED, headers={"request-id": "req_test"})

    client = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    reply = get_llm("skill", http_client=client).invoke([HumanMessage("Reply OK")])

    assert reply.content == "OK"
    (req,) = seen
    body = json.loads(req.content)
    assert req.url.path == "/v1/messages"
    assert body["model"] == "claude-sonnet-5-5"
    assert "temperature" not in body  # rejected by current models
    assert body["output_config"] == {"effort": "medium"}


def test_router_tier_sends_no_effort(live_settings):
    seen = []
    client = anthropic.DefaultHttpxClient(
        transport=httpx2.MockTransport(lambda r: seen.append(r) or httpx2.Response(200, json=CANNED))
    )
    get_llm("router", http_client=client).invoke([HumanMessage("hi")])
    assert "output_config" not in json.loads(seen[0].content)  # Haiku 4.5 rejects effort


def test_build_http_clients_defaults_to_sdk(live_settings):
    assert build_http_clients() == (None, None)


def test_build_http_clients_from_settings(live_settings, monkeypatch):
    monkeypatch.setenv("LLM_PROXY_URL", "http://proxy.corp.local:8080")
    monkeypatch.setenv("LLM_TIMEOUT_S", "120")
    get_settings.cache_clear()
    sync, async_ = build_http_clients()
    assert isinstance(sync, anthropic.DefaultHttpxClient)
    assert isinstance(async_, anthropic.DefaultAsyncHttpxClient)
    assert sync.timeout.read == 120
