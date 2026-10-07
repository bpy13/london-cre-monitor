"""Tool catalogue available to skills.

Skills reference tools *by name* in their SKILL.md ``tools`` list; the
skill runner calls :func:`get_tools` to bind exactly that subset to the
skill's sub-agent (least privilege - the news skill cannot, for example,
call the macro APIs unless its author allows it).

To add a tool: implement it as a LangChain ``@tool`` in this package (with
an offline fixture path!) and register it in :data:`TOOLS`.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from cre_monitor.tools.documents import fetch_document
from cre_monitor.tools.history import metrics_history
from cre_monitor.tools.macro import boe_series, ons_series
from cre_monitor.tools.news import rss_news
from cre_monitor.tools.search import web_search

#: name -> tool. Names must match the ``tools`` entries in SKILL.md files.
TOOLS: dict[str, BaseTool] = {
    t.name: t
    for t in (web_search, fetch_document, rss_news, boe_series, ons_series, metrics_history)
}

TOOL_NAMES: tuple[str, ...] = tuple(TOOLS)


def get_tools(names: list[str]) -> list[BaseTool]:
    """Return tool objects for ``names`` (order preserved).

    Raises:
        KeyError: If a name is not in :data:`TOOLS` (the registry validates
        SKILL.md files up front, so this indicates a programming error).
    """
    return [TOOLS[n] for n in names]


__all__ = ["TOOLS", "TOOL_NAMES", "get_tools"]
