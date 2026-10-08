"""Central configuration, loaded from environment variables and ``.env``.

All tunables live here so that nothing else in the codebase reads
``os.environ`` directly. Import the singleton via :func:`get_settings`.

Two switches control how "real" a run is - they are independent:

* ``CRE_OFFLINE`` - data tools read from ``fixtures/`` instead of the
  internet. Use for deterministic demos and tests.
* ``CRE_DEMO_MODE`` - no LLM calls at all. Skill findings are loaded from
  ``fixtures/findings/`` and synthesis/chat answers are rule-based. This
  lets anyone run the whole pipeline (graph, charts, report, UI) without an
  API key. Defaults to ``True`` automatically when ``ANTHROPIC_API_KEY`` is
  missing, so a fresh checkout "just works".
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Repository root (``src/cre_monitor/config.py`` -> three levels up).
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime settings. Every field can be overridden by an env variable of
    the same name (case-insensitive), e.g. ``MODEL_SKILL=claude-opus-5-5``."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Credentials -------------------------------------------------------
    anthropic_api_key: str | None = None
    tavily_api_key: str | None = None

    # --- Models (one per "tier"; skills pick a tier in their frontmatter) --
    # router: cheap/fast, used to pick skills for a chat question.
    # skill:  workhorse for the tool-using research sub-agents.
    # synthesis: strongest model, writes the executive summary / answers.
    model_router: str = "claude-haiku-4-5-20251001"
    model_skill: str = "claude-sonnet-5-5"
    model_synthesis: str = "claude-opus-5-5"
    # Reasoning effort per tier (low|medium|high|xhigh|max). This is the main
    # cost/quality dial on current models - they don't accept a custom
    # `temperature`, and thinking is on by default. Haiku 4.5 (router) does not
    # support effort, so the router tier has none.
    effort_skill: str = "medium"
    effort_synthesis: str = "high"
    #: Output cap per call. Thinking tokens count towards it, so keep it generous
    #: (a truncated structured response fails validation and wastes the call).
    llm_max_tokens: int = 16000

    # --- Run modes (see module docstring) ---------------------------------
    cre_offline: bool = False
    cre_demo_mode: bool | None = None  # None -> derived from API key presence

    # --- Agent behaviour ---------------------------------------------------
    #: Max ReAct steps (LLM turn + tool calls) per skill sub-agent. Caps cost
    #: and prevents a confused agent from looping forever.
    skill_max_steps: int = 12
    #: Metrics older than this many days are flagged as stale by the validator.
    stale_after_days: int = 200
    #: Two sources disagreeing by more than this (in the metric's own units,
    #: percentage points for rates) is flagged as a conflict.
    conflict_tolerance_pct_points: float = 1.5
    conflict_tolerance_rent_pct: float = 10.0

    # --- UI ----------------------------------------------------------------
    #: Debug mode for the Streamlit UI: show Streamlit's developer toolbar
    #: (Rerun, Clear cache, ...). Off by default for business users. Same as
    #: `cre-monitor ui --debug`.
    cre_ui_debug: bool = False

    # --- Support -----------------------------------------------------------
    #: Who users should contact when an error panel shows a reference ID, e.g.
    #: "Jane Doe (jane.doe@nanfung.com)" or "#london-cre-support on Teams".
    support_contact: str = "the London engineering team"

    # --- Reporting ---------------------------------------------------------
    #: Export static PNG charts for the Markdown report (needs a local Chrome
    #: for kaleido). Tests switch it off for speed.
    report_png: bool = True

    # --- Paths -------------------------------------------------------------
    skills_dir: Path = PROJECT_ROOT / "skills"
    fixtures_dir: Path = PROJECT_ROOT / "fixtures"
    data_dir: Path = PROJECT_ROOT / "data"
    reports_dir: Path = PROJECT_ROOT / "reports"
    #: Where `cre-monitor export` writes its zip files (git-ignored).
    exports_dir: Path = PROJECT_ROOT / "exports"

    # --- HTTP --------------------------------------------------------------
    http_timeout_s: float = 30.0
    #: Some public endpoints (notably the Bank of England) reject requests
    #: without a browser-like User-Agent.
    http_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) cre-monitor/0.1 (research PoC)"
    )

    @model_validator(mode="after")
    def _derive_demo_mode(self) -> "Settings":
        """Enable demo mode automatically when no Anthropic key is configured."""
        if self.cre_demo_mode is None:
            self.cre_demo_mode = not bool(self.anthropic_api_key)
        return self

    # Convenience paths ------------------------------------------------------
    @property
    def metrics_db_path(self) -> Path:
        """SQLite file holding the metric time series across runs."""
        return self.data_dir / "metrics.sqlite"

    @property
    def checkpoint_db_path(self) -> Path:
        """SQLite file used by LangGraph's checkpointer (chat memory)."""
        return self.data_dir / "checkpoints.sqlite"

    @property
    def conversations_db_path(self) -> Path:
        """SQLite file indexing chat conversations and their turns (sidebar history)."""
        return self.data_dir / "conversations.sqlite"

    def ensure_dirs(self) -> None:
        """Create writable directories if they do not exist yet."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Tests that need different settings should call ``get_settings.cache_clear()``
    after patching environment variables.
    """
    return Settings()  # type: ignore[call-arg]


#: Re-exported so callers can type-annotate without importing pydantic.
__all__ = ["Settings", "get_settings", "PROJECT_ROOT", "Field"]
