"""A scripted chat model for testing the LLM code paths without an API key.

``ScriptedChatModel`` plays back pre-defined ``AIMessage`` objects (which may
contain tool calls) and returns pre-built objects for structured-output
calls. It records every prompt it receives so tests can assert on what the
agent actually sent (e.g. that tool results reached the model).
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import Field


class ScriptedChatModel(BaseChatModel):
    """Fake LLM. Not thread-safe: use with one skill at a time."""

    responses: list[AIMessage] = Field(default_factory=list)
    #: schema class name -> object returned by ``with_structured_output(schema)``
    structured: dict[str, Any] = Field(default_factory=dict)
    calls: list[list[BaseMessage]] = Field(default_factory=list)
    #: Parallel to ``calls``: "chat" or "structured:<Schema>" - lets tests check *how* the model was called.
    kinds: list[str] = Field(default_factory=list)
    #: Tool names of every ``bind_tools`` call, in order.
    bound_tools: list[list[str]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append(list(messages))
        self.kinds.append("chat")
        msg = self.responses.pop(0) if self.responses else AIMessage("No more scripted responses.")
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools, **kwargs):  # tools are executed by ToolNode, not the model
        self.bound_tools.append([t["name"] if isinstance(t, dict) else t.name for t in tools])
        return self

    def with_structured_output(self, schema, **kwargs):
        def respond(messages):
            self.calls.append(list(messages) if isinstance(messages, list) else [messages])
            self.kinds.append(f"structured:{schema.__name__}")
            return self.structured[schema.__name__].model_copy(deep=True)

        return RunnableLambda(respond)


def submit_call(finding, call_id: str = "submit-1") -> AIMessage:
    """An AIMessage that calls ``submit_finding`` with a finding's content (minus bookkeeping fields)."""
    args = finding.model_dump(mode="json", exclude={"skill", "error"})
    return AIMessage("", tool_calls=[tool_call("submit_finding", args, call_id)])


def tool_call(name: str, args: dict, call_id: str) -> dict:
    """Shape of a tool call inside ``AIMessage.tool_calls``."""
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}
