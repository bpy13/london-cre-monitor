"""Command-line interface: ``cre-monitor <command>``.

Commands
--------
``brief``     Run the full market brief once and write the report.
``ask``       Ask a single question (chat mode).
``chat``      Interactive multi-turn chat in the terminal.
``briefs``    List generated briefs, or delete one (``briefs delete <id>``).
``conversations``  List saved chat conversations.
``export``    Export briefs, metrics and conversations as one zip (CSV/Excel/Markdown/JSON).
``merge``     Merge another installation's data/ (and reports/) into this one.
``style``     House style: ``learn`` from example reports, ``show``, ``clear``.
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
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from cre_monitor.config import PROJECT_ROOT, get_settings

app = typer.Typer(add_completion=False, help="London CRE Market Monitor - LangGraph agent PoC.")
schedule_app = typer.Typer(help="Manage the recurring scheduled brief.")
app.add_typer(schedule_app, name="schedule")
briefs_app = typer.Typer(help="List or delete generated briefs.")
app.add_typer(briefs_app, name="briefs")
style_app = typer.Typer(help="House style: learn from example reports and apply it to briefs.")
app.add_typer(style_app, name="style")
console = Console()

TASK_NAME = "LondonCREMonitorBrief"


def _setup_logging(log_name: str, console_level: int = logging.INFO) -> Path:
    """Log to ``data/logs/<log_name>_<date>.log`` (the file matters for scheduled
    runs, which have no console). See :func:`cre_monitor.logs.setup_logging`."""
    from cre_monitor.logs import setup_logging

    return setup_logging(log_name, console_level)


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
    no_style: bool = typer.Option(False, "--no-style", help="Ignore the learned house style for this brief."),
) -> None:
    """Run the full London office market brief and write HTML/Markdown reports."""
    log_file = _setup_logging("brief")
    _mode_banner()
    from cre_monitor.graph.builder import run_brief
    from cre_monitor.style import active_profile

    if (profile := active_profile(not no_style)) is not None:
        console.print(f"[dim]House style: {profile.name}[/dim]")

    selected = [s.strip() for s in skills.split(",")] if skills else None
    with console.status("Running skills and building the brief..."):
        state = run_brief(selected, use_style=not no_style)
    paths = state.get("report_paths", {})
    issues = state.get("validation_issues", [])
    failed = [f.skill for f in state.get("findings", []) if f.error]
    console.print(f"[green]Brief complete[/green] - {len(state.get('findings', []))} skills, "
                  f"{len(issues)} data-quality notes, {len(failed)} failed {failed or ''}")
    for kind, path in paths.items():
        console.print(f"  {kind:9} {path}")
    console.print(f"  log       {log_file}")
    _print_incident(state.get("incident"))
    if open_report and "html" in paths:
        webbrowser.open(Path(paths["html"]).as_uri())


def _print_incident(incident) -> None:
    """Terminal version of the UI error panel: plain-English problem + traceable reference."""
    if incident is None:
        return
    cat = incident.category
    total = incident.scope == "total"
    lead = "Could not answer." if total else "Part of the research failed - the result may be incomplete."
    body = (
        f"[bold]{cat.title}[/bold]\n{lead} {cat.message}\n\n"
        + "\n".join(f"• {a}" for a in cat.actions)
        + f"\n\nReference for support: [bold]{incident.id}[/bold]  (send to {get_settings().support_contact})"
        + f"\n[dim]Affected: {', '.join(incident.affected)} · details in {incident.log_file or 'the log'}[/dim]"
    )
    console.print(Panel(body, title="Problem" if total else "Warning", border_style="red" if total else "yellow"))


def _resolve_thread(thread: str | None) -> str:
    """Return the thread to use: the given one (announcing a resume) or a new one."""
    from cre_monitor.graph.builder import new_thread_id
    from cre_monitor.store import get_conversation_store

    if thread:
        existing = get_conversation_store().get(thread)
        if existing:
            console.print(f"[dim]Resuming '{existing.title}' ({existing.turn_count} earlier question(s))[/dim]")
        return thread
    thread = new_thread_id()
    console.print(f"[dim]New conversation {thread} - continue later with --thread {thread}[/dim]")
    return thread


REF_HELP = ("Earlier conversation id to use as background context (repeatable, max 3; "
            "see `cre-monitor conversations`). Figures are still refreshed from current research.")


def _resolve_refs(thread: str, refs: list[str] | None) -> list[str]:
    """Validate --ref values, warn about any that are ignored, and list the ones used."""
    from cre_monitor.graph.builder import resolve_refs
    from cre_monitor.store import get_conversation_store

    used = resolve_refs(thread, refs)
    ignored = [r for r in refs or [] if r not in used]
    if ignored:
        console.print(f"[yellow]Ignoring --ref {', '.join(ignored)} (unknown, current conversation, duplicate or over the limit of 3)[/yellow]")
    store = get_conversation_store()
    for r in used:
        console.print(f"[dim]📎 Referencing '{store.get(r).title}' ({r})[/dim]")
    return used


@app.command()
def ask(
    question: str,
    thread: str = typer.Option(None, help="Conversation id to continue (see `cre-monitor conversations`). Omit for a new one."),
    ref: list[str] = typer.Option(None, "--ref", help=REF_HELP),
) -> None:
    """Ask one question about the London office market."""
    _setup_logging("chat", console_level=logging.WARNING)
    _mode_banner()
    from cre_monitor.graph.builder import ask as ask_graph

    thread = _resolve_thread(thread)
    refs = _resolve_refs(thread, ref)
    with console.status("Researching..."):
        state = ask_graph(question, thread_id=thread, refs=refs)
    console.print(f"[dim]Skills used: {', '.join(state.get('selected_skills') or ['none'])}[/dim]")
    console.print(Markdown(state.get("answer", "")))
    _print_incident(state.get("incident"))


@app.command()
def chat(
    thread: str = typer.Option(None, help="Conversation id to resume (see `cre-monitor conversations`). Omit for a new one."),
    ref: list[str] = typer.Option(None, "--ref", help=REF_HELP + " Applies to every question in this session."),
) -> None:
    """Interactive terminal chat. Type 'exit' to quit."""
    _setup_logging("chat", console_level=logging.WARNING)
    _mode_banner()
    from cre_monitor.graph.builder import ask as ask_graph

    thread = _resolve_thread(thread)
    refs = _resolve_refs(thread, ref)
    console.print("Ask about London offices (rents, vacancy, take-up, pipeline, submarkets, macro, ESG, news).")
    while True:
        try:
            question = console.input("[bold cyan]you> [/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if question.lower() in {"exit", "quit", ""}:
            break
        with console.status("Researching..."):
            state = ask_graph(question, thread_id=thread, refs=refs)
        console.print(f"[dim]Skills: {', '.join(state.get('selected_skills') or ['none'])}[/dim]")
        console.print(Markdown(state.get("answer", "")))
        _print_incident(state.get("incident"))


@app.command("conversations")
def list_conversations(limit: int = typer.Option(20, help="How many to show (most recent first).")) -> None:
    """List saved chat conversations (resume one with `cre-monitor chat --thread <id>`)."""
    from cre_monitor.store import get_conversation_store

    conversations = get_conversation_store().list(limit=limit)
    if not conversations:
        console.print("No conversations yet.")
        return
    table = Table("Thread", "Title", "Questions", "Last active")
    for c in conversations:
        table.add_row(c.thread_id, c.title, str(c.turn_count), f"{c.updated_at:%Y-%m-%d %H:%M}")
    console.print(table)
    console.print("[dim]Resume: cre-monitor chat --thread <Thread>   ·   UI: open ?thread=<Thread>[/dim]")


@style_app.command("learn")
def style_learn(
    source: Path = typer.Option(None, "--from", help="Folder of example reports (default: style/reports/)."),
    heuristic: bool = typer.Option(False, "--heuristic", help="Use the offline heuristic instead of the LLM."),
) -> None:
    """Learn the house style from example reports (.md/.txt/.html/.pdf) and save style/profile.json."""
    _setup_logging("style", console_level=logging.WARNING)
    from cre_monitor.style import learn_profile
    from cre_monitor.style.profile import profile_path

    try:
        with console.status("Analysing example reports..."):
            profile = learn_profile(source, use_llm=False if heuristic else None)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]Learned[/green] '{profile.name}' via {profile.method} from {len(profile.sources)} report(s).")
    console.print(f"  Review / edit: {profile_path()} (readable copy: {profile_path().with_suffix('.md')})")
    console.print("  It now applies to every brief (layout, executive summary, topic wording). "
                  "Use `brief --no-style` or REPORT_STYLE=0 to switch it off.")


@style_app.command("show")
def style_show() -> None:
    """Show the current house style profile."""
    from cre_monitor.style import load_profile

    profile = load_profile()
    if profile is None:
        console.print("No house style learned yet. Put example reports in style/reports/ and run `cre-monitor style learn`.")
        return
    console.print(Markdown(profile.to_markdown()))
    if not get_settings().report_style:
        console.print("[yellow]REPORT_STYLE=0: the profile is currently NOT applied to briefs.[/yellow]")


@style_app.command("clear")
def style_clear() -> None:
    """Delete the house style profile (briefs return to the built-in style)."""
    from cre_monitor.style import clear_profile

    console.print("Profile removed." if clear_profile() else "No profile to remove.")


@briefs_app.command("list")
def briefs_list(limit: int = typer.Option(20, help="How many to show (newest first).")) -> None:
    """List generated briefs with their ids."""
    from cre_monitor.reporting.briefs import list_briefs

    briefs = list_briefs()[:limit]
    if not briefs:
        console.print("No briefs yet. Run `cre-monitor brief`.")
        return
    table = Table("Brief id", "Created", "HTML report")
    for b in briefs:
        table.add_row(b.run_id, f"{b.created_at:%Y-%m-%d %H:%M}", str(b.html))
    console.print(table)


@briefs_app.command("delete")
def briefs_delete(
    run_id: str = typer.Argument(..., help="Brief id from `cre-monitor briefs list`."),
    with_metrics: bool = typer.Option(
        False, "--with-metrics", help="Also remove the brief's figures from the metrics history (affects deltas/trends).",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask for confirmation."),
) -> None:
    """Delete a brief's files (HTML, Markdown, findings JSON, charts)."""
    from cre_monitor.reporting.briefs import delete_brief, get_brief

    brief = get_brief(run_id)
    if brief is None:
        console.print(f"[red]No brief with id {run_id!r}.[/red] See `cre-monitor briefs list`.")
        raise typer.Exit(code=1)
    what = "brief and its metrics history" if with_metrics else "brief"
    if not yes and not typer.confirm(f"Permanently delete {what} {run_id}?"):
        raise typer.Exit()
    removed = delete_brief(run_id, with_metrics=with_metrics)
    console.print(f"[green]Deleted[/green] {what} {run_id} ({len(removed)} files/folders).")


@app.command("export")
def export(
    out: Path = typer.Option(None, "--out", help="Folder for the zip (default: exports/)."),
    since: str = typer.Option(None, "--since", help="Only data from this date on, YYYY-MM-DD."),
    include_logs: bool = typer.Option(False, "--include-logs", help="Also include data/logs (for engineers)."),
) -> None:
    """Export briefs, metrics history and conversations as one zip (with an Excel workbook)."""
    from datetime import date as _date

    from cre_monitor.export import export_data

    since_date = None
    if since:
        try:
            since_date = _date.fromisoformat(since)
        except ValueError:
            console.print(f"[red]--since must be YYYY-MM-DD, got {since!r}[/red]")
            raise typer.Exit(code=2)
    with console.status("Exporting..."):
        result = export_data(out_dir=out, since=since_date, include_logs=include_logs)
    c = result.counts
    console.print(f"[green]Exported[/green] {result.path}")
    console.print(f"  {c['metric_rows']} metric rows · {c['briefs']} briefs · "
                  f"{c['conversations']} conversations ({c['turns']} questions) · {c['log_files']} log files")


def _print_merge(report) -> None:
    c = report.conversations
    table = Table("Data", "Result")
    table.add_row("Metrics", f"+{report.metrics_added} rows ({report.metrics_skipped} already present / seed)")
    table.add_row("Conversations", f"{len(c['added'])} added · {len(c['extended'])} extended · "
                                   f"{len(c['renamed'])} renamed · {len(c['skipped'])} already present "
                                   f"(+{report.turns_added} questions)")
    table.add_row("Agent memory", f"{report.checkpoint_threads_copied} threads ({report.checkpoint_rows_copied} rows)")
    table.add_row("Brief files", "not merged" if report.source_reports is None else
                  f"+{report.report_files_copied}" + (f" · {len(report.report_conflicts)} conflicts (kept target's)"
                                                       if report.report_conflicts else ""))
    console.print(table)
    for entry in c["renamed"]:
        console.print(f"[yellow]Renamed (same id, different history): {entry}[/yellow]")


@app.command("merge")
def merge(
    source: Path = typer.Argument(..., help="Other installation's project folder (with data/) or its data/ folder."),
    no_reports: bool = typer.Option(False, "--no-reports", help="Don't merge brief files from reports/."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only show what would change."),
    no_backup: bool = typer.Option(
        False, "--no-backup",
        help="Skip the automatic backup. Not recommended: it also disables automatic restore if the merge fails.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't preview/ask for confirmation."),
) -> None:
    """Merge another installation's data (metrics, conversations, agent memory, briefs) into this one.

    Safe to re-run: existing data is never overwritten and already-merged data is skipped.
    Stop both apps first.
    """
    _setup_logging("merge", console_level=logging.WARNING)
    from cre_monitor.errors import incident_from_exception
    from cre_monitor.store.merge import MergeError, merge_installation

    kwargs = {"include_reports": not no_reports}
    try:
        if dry_run or not yes:
            preview = merge_installation(source, dry_run=True, **kwargs)
            console.print(f"[bold]{'Dry run' if dry_run else 'Preview'}:[/bold] merge {preview.source_data} → "
                          f"{get_settings().data_dir}")
            _print_merge(preview)
            if dry_run or not typer.confirm("Apply this merge?"):
                raise typer.Exit()
        result = merge_installation(source, backup=not no_backup, **kwargs)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    except MergeError as exc:
        incident = incident_from_exception(exc, step="merge")
        outcome = ("Your data was restored to its pre-merge state." if exc.restored
                   else "Nothing was changed.")
        console.print(Panel(f"[bold]The merge did not complete.[/bold] {outcome}\n\n{exc}\n\n"
                            f"Reference for support: [bold]{incident.id}[/bold]",
                            title="Merge failed", border_style="red"))
        raise typer.Exit(code=1)
    console.print("[green]Merged.[/green]" + (f" Backup of the previous data: {result.backup}" if result.backup else ""))
    if yes:
        _print_merge(result)


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
def ui(
    port: int = 8501,
    debug: bool = typer.Option(
        False, "--debug",
        help="Show Streamlit's developer toolbar (Rerun, Clear cache, ...). Also enabled by CRE_UI_DEBUG=1.",
    ),
) -> None:
    """Launch the Streamlit chat UI and dashboard."""
    app_path = Path(__file__).parent / "ui" / "app.py"
    # Business users get the "viewer" toolbar (no Deploy/Rerun/Clear cache);
    # debug mode restores Streamlit's full developer toolbar. Passed explicitly so
    # it works from any launch folder (mirrors .streamlit/config.toml).
    toolbar = "developer" if (debug or get_settings().cre_ui_debug) else "viewer"
    if toolbar == "developer":
        console.print("[yellow]UI debug mode: Streamlit developer toolbar enabled (Rerun, Clear cache, Deploy).[/yellow]")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", str(port),
         "--client.toolbarMode", toolbar],
        check=False,
    )


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
