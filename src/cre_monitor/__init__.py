"""London CRE Market Monitor.

A LangGraph agent that monitors the London office market (rents, vacancy,
take-up, supply pipeline, submarkets, macro, occupier demand and news) and
produces cited, chart-backed market briefs and chat answers.

The agent is organised around *skills*: self-contained folders under
``skills/`` that each describe one research area in a ``SKILL.md`` file.
See ``docs/ARCHITECTURE.md`` and ``docs/SKILLS.md`` for the big picture.
"""

__version__ = "0.1.0"
