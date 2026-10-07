"""Command-line interface: ``cre-monitor <command>``.

Commands
--------
``brief``     Run the full market brief once and write the report.
``ask``       Ask a single question (chat mode).
``chat``      Interactive multi-turn chat in the terminal.
``skills``    List loaded skills (and any invalid SKILL.md files).
``schedule``  Install / remove / show the weekly scheduled brief (Windows
              Task Scheduler; prints a cron line for Linux/macOS).
``ui``        Launch the Streamlit chat UI and dashboard.

Global flags ``--offline`` and ``--demo/--live`` override the corresponding
settings for one invocation (see ``config.py`` for what they mean).
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
import webbrowser
from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from cre_monitor.config import PROJECT_ROOT, get_settings

app = typer.Typer(add_completion=False, help="London CRE Market Monitor - LangGraph agent PoC.")
schedule_app = typer.Typer(help="Manage the recurring scheduled brief.")
app.add_typer(schedule_app, name="schedule")
console = Console()

TASK_NAME = "LondonCREMonitorBrief"


def _setup_logging(log_name: str, console_level: int = logging.INFO) -> Path:
    """Log INFO to ``data/logs/<log_name>_<date>.log`` and ``console_level`` to the console.

    The log file matters for scheduled runs, which have no visible console.
    Interactive commands (ask/chat) pass WARNING so answers aren't buried in logs.
    """
    s = get_settings()
    log_dir = s.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{log_name}_{date.today().isoformat()}.log"
    console = logging.StreamHandler()
    console.setLevel(console_level)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[console, logging.FileHandler(log_file, encoding="utf-8")],
        force=True,
    )
    # Third-party libraries are chatty at INFO.
    for noisy in ("httpx", "httpcore", "anthropic", "trafilatura", "kaleido", "choreographer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return log_file


@app.callback()
def main(
    offline: bool = typer.Option(None, "--offline/--online", help="Use fixture data instead of the internet."),
    demo: bool = typer.Option(None, "--demo/--live", help="Demo mode: no LLM calls (canned findings)."),
) -> None:
    """Apply global flags by setting env vars, then rebuild the settings singleton."""
    if offline is not None:
        os.environ["CRE_OFFLINE"] = "1" if offline else "0"
    if demo is not None:
        os.environ["CRE_DEMO_MODE"] = "1" if demo else "0"
    get_settings.cache_clear()
    s = get_settings()
    if not s.cre_demo_mode and not s.anthropic_api_key:
        console.print("[red]--live requires ANTHROPIC_API_KEY (set it in .env).[/red]")
        raise typer.Exit(code=2)


def _mode_banner() -> None:
    s = get_settings()
    llm = "demo (no LLM)" if s.cre_demo_mode else f"live ({s.model_skill} / {s.model_synthesis})"
    data = "offline fixtures" if s.cre_offline else ("Tavily + public APIs" if s.tavily_api_key else "Google News + public APIs")
    console.print(f"[dim]LLM: {llm} | Data: {data}[/dim]")


@app.command()
def brief(
    skills: str = typer.Option(None, help="Comma-separated subset of skills, e.g. 'office-rents,macro-economy'."),
    open_report: bool = typer.Option(False, "--open", help="Open the HTML report when done."),
) -> None:
    """Run the full London office market brief and write HTML/Markdown reports."""
    log_file = _setup_logging("brief")
    _mode_banner()
    from cre_monitor.graph.builder import run_brief

    selected = [s.strip() for s in skills.split(",")] if skills else None
    with console.status("Running skills and building the brief..."):
        state = run_brief(selected)
    paths = state.get("report_paths", {})
    issues = state.get("validation_issues", [])
    failed = [f.skill for f in state.get("findings", []) if f.error]
    console.print(f"[green]Brief complete[/green] - {len(state.get('findings', []))} skills, "
                  f"{len(issues)} data-quality notes, {len(failed)} failed {failed or ''}")
    for kind, path in paths.items():
        console.print(f"  {kind:9} {path}")
    console.print(f"  log       {log_file}")
    if open_report and "html" in paths:
        webbrowser.open(Path(paths["html"]).as_uri())


@app.command()
def ask(question: str, thread: str = typer.Option("cli", help="Conversation id for follow-ups.")) -> None:
    """Ask one question about the London office market."""
    _setup_logging("chat", console_level=logging.WARNING)
    _mode_banner()
    from cre_monitor.graph.builder import ask as ask_graph

    with console.status("Researching..."):
        state = ask_graph(question, thread_id=thread)
    console.print(f"[dim]Skills used: {', '.join(state.get('selected_skills') or ['none'])}[/dim]")
    console.print(Markdown(state.get("answer", "")))


@app.command()
def chat(thread: str = typer.Option("cli-chat", help="Conversation id (reuse to continue).")) -> None:
    """Interactive terminal chat. Type 'exit' to quit."""
    _setup_logging("chat", console_level=logging.WARNING)
    _mode_banner()
    from cre_monitor.graph.builder import ask as ask_graph

    console.print("Ask about London offices (rents, vacancy, take-up, pipeline, submarkets, macro, ESG, news).")
    while True:
        try:
            question = console.input("[bold cyan]you> [/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if question.lower() in {"exit", "quit", ""}:
            break
        with console.status("Researching..."):
            state = ask_graph(question, thread_id=thread)
        console.print(f"[dim]Skills: {', '.join(state.get('selected_skills') or ['none'])}[/dim]")
        console.print(Markdown(state.get("answer", "")))


@app.command("skills")
def list_skills() -> None:
    """List skills discovered under skills/ and any that failed validation."""
    from cre_monitor.skills import get_registry

    reg = get_registry()
    table = Table("Skill", "Tools", "In brief", "Description")
    for s in reg.all():
        table.add_row(s.name, ", ".join(s.meta.tools) or "-", "yes" if s.meta.in_brief else "no",
                      s.meta.description[:90] + ("..." if len(s.meta.description) > 90 else ""))
    console.print(table)
    for name, err in reg.errors.items():
        console.print(f"[red]INVALID {name}: {err}[/red]")


@app.command()
def ui(port: int = 8501) -> None:
    """Launch the Streamlit chat UI and dashboard."""
    app_path = Path(__file__).parent / "ui" / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", str(port)], check=False)


# --------------------------------------------------------------------------
# Scheduling
# --------------------------------------------------------------------------

def _brief_command() -> str:
    """Absolute command line that runs the brief with this environment's Python."""
    return f'"{sys.executable}" -m cre_monitor.cli brief'


@schedule_app.command("install")
def schedule_install(
    day: str = typer.Option("MON", help="Day of week: MON..SUN."),
    time: str = typer.Option("07:00", help="24h start time, HH:MM (local time)."),
) -> None:
    """Register a weekly brief. Windows: Task Scheduler. Others: prints a crontab line."""
    day = day.upper()[:3]
    if platform.system() != "Windows":
        hh, mm = time.split(":")
        dow = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6}[day]
        console.print("Add this line with `crontab -e`:")
        console.print(f"{int(mm)} {int(hh)} * * {dow} cd {PROJECT_ROOT} && {_brief_command()}")
        return
    cmd = ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", _brief_command(),
           "/SC", "WEEKLY", "/D", day, "/ST", time, "/F"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        console.print(f"[green]Scheduled[/green] '{TASK_NAME}' every {day} at {time}. Logs: data/logs/")
    else:
        console.print(f"[red]schtasks failed:[/red] {result.stderr or result.stdout}")
        raise typer.Exit(code=1)


@schedule_app.command("remove")
def schedule_remove() -> None:
    """Remove the scheduled brief (Windows)."""
    result = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, text=True)
    console.print(result.stdout or result.stderr)


@schedule_app.command("show")
def schedule_show() -> None:
    """Show the scheduled task status (Windows) and the exact command it runs."""
    console.print(f"Command: {_brief_command()}")
    if platform.system() == "Windows":
        result = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"], capture_output=True, text=True)
        if result.returncode != 0:
            console.print(f"Task '{TASK_NAME}' is not scheduled. Run `cre-monitor schedule install`.")
        else:
            console.print(result.stdout)


if __name__ == "__main__":  # allows `python -m cre_monitor.cli ...` (used by the scheduler)
    app()
