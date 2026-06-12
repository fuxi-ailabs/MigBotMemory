"""CLI entry point — typer-based command interface."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from .config import MBMConfig
from .inject import BriefingGenerator
from .models import Outcome, Phase, QualityMetrics, SkillEvent, TaskRecord
from .store import TaskStore

app = typer.Typer(
    name="mbm",
    help="MigBotMemory — task lifecycle memory for code migration",
    no_args_is_help=True,
)


def _load_config() -> MBMConfig:
    return MBMConfig.load(Path.cwd())


def _load_store(config: MBMConfig) -> TaskStore:
    return TaskStore(config)


# ── init ──────────────────────────────────────────────────────────

@app.command()
def init(
    domain: str = typer.Option("default", help="Migration domain tag"),
) -> None:
    """Initialize .mbm directory structure."""
    config = MBMConfig(domain=domain, mbm_dir=str(Path.cwd() / ".mbm"))
    config.save()
    store = _load_store(config)
    typer.echo(f"Initialized MigBotMemory at {config.root} (domain: {domain})")


# ── briefing ──────────────────────────────────────────────────────

@app.command()
def briefing(
    domain: Optional[str] = typer.Option(None, help="Filter by domain"),
    write: bool = typer.Option(False, "--write", help="Write briefing.md to .mbm/context/"),
) -> None:
    """Generate progressive disclosure briefing."""
    config = _load_config()
    store = _load_store(config)
    gen = BriefingGenerator(store, config)

    if write:
        content = gen.generate_and_write(domain)
        typer.echo(f"Briefing written to {config.context_dir / 'briefing.md'}")
    else:
        typer.echo(gen.generate(domain))


# ── record ────────────────────────────────────────────────────────

@app.command()
def record(
    id: str = typer.Option(..., help="Task identifier"),
    domain: str = typer.Option("default", help="Migration domain"),
    feature: str = typer.Option(..., help="Feature name, e.g. 'LoginActivity'"),
    source: str = typer.Option(..., help="Source file/component"),
    target: str = typer.Option(..., help="Target file/component"),
    task_summary: str = typer.Option("", help="What was defined"),
    plan_summary: str = typer.Option("", help="Design decisions"),
    execute_summary: str = typer.Option("", help="Implementation approach"),
    verify_summary: str = typer.Option("", help="Verification results"),
    commit_summary: str = typer.Option("", help="What was committed"),
    key_decisions: Optional[str] = typer.Option(None, help="JSON array of key decisions"),
    key_errors: Optional[str] = typer.Option(None, help="JSON array of key errors"),
    key_fixes: Optional[str] = typer.Option(None, help="JSON array of key fixes"),
    outcome: Outcome = typer.Option(Outcome.failed, help="Task outcome"),
    compile_pass: bool = typer.Option(False, help="Did compilation pass?"),
    lint_errors: int = typer.Option(0, help="Lint error count"),
    test_pass: bool = typer.Option(False, help="Did tests pass?"),
    verify_pass: bool = typer.Option(False, help="Did verification pass?"),
) -> None:
    """Record a complete feature migration lifecycle."""
    config = _load_config()
    store = _load_store(config)

    task = TaskRecord(
        id=id,
        domain=domain,
        feature=feature,
        source=source,
        target=target,
        task_summary=task_summary,
        plan_summary=plan_summary,
        execute_summary=execute_summary,
        verify_summary=verify_summary,
        commit_summary=commit_summary,
        key_decisions=json.loads(key_decisions) if key_decisions else [],
        key_errors=json.loads(key_errors) if key_errors else [],
        key_fixes=json.loads(key_fixes) if key_fixes else [],
        outcome=outcome,
        quality=QualityMetrics(
            compile_pass=compile_pass,
            lint_errors=lint_errors,
            test_pass=test_pass,
            verify_pass=verify_pass,
        ),
        completed_at=datetime.now(timezone.utc),
    )

    store.write_task(task)
    category = task.category
    typer.echo(f"Task recorded: {id} → {category} (outcome={outcome.value})")


# ── event ─────────────────────────────────────────────────────────

@app.command()
def event(
    skill_name: str = typer.Option(..., help="Skill name that was invoked"),
    skill_args: Optional[str] = typer.Option(None, help="Skill arguments"),
    output_summary: Optional[str] = typer.Option(None, help="Compressed output summary"),
) -> None:
    """Record a skill invocation event (called by PostToolUse hook)."""
    config = _load_config()
    store = _load_store(config)

    phase = config.resolve_phase(skill_name)

    evt = SkillEvent(
        skill_name=skill_name,
        skill_args=skill_args,
        phase=phase,
        output_summary=output_summary,
    )

    store.append_event(evt)
    phase_str = phase.value if phase else "unknown"
    typer.echo(f"Event recorded: {skill_name} → phase={phase_str}")


# ── lookup ────────────────────────────────────────────────────────

@app.command()
def lookup(
    task_id: str = typer.Argument(help="Task ID to look up"),
) -> None:
    """Lookup full task lifecycle details (lossless, on-demand)."""
    config = _load_config()
    store = _load_store(config)

    task = store.read_task(task_id)
    if task is None:
        typer.echo(f"Task not found: {task_id}", err=True)
        raise typer.Exit(1)

    typer.echo(task.model_dump_json(indent=2))


# ── search ────────────────────────────────────────────────────────

@app.command()
def search(
    feature: str = typer.Argument(help="Feature name to search for"),
    domain: Optional[str] = typer.Option(None, help="Filter by domain"),
) -> None:
    """Search tasks by feature name."""
    config = _load_config()
    store = _load_store(config)

    results = store.lookup_by_feature(feature, domain)
    if not results:
        typer.echo("No matching tasks found.")
        return

    for t in results:
        typer.echo(
            f"{t.id} | {t.category} | {t.outcome.value} | "
            f"{t.source} → {t.target} | {t.feature}"
        )


# ── checkpoint ────────────────────────────────────────────────────

@app.command()
def checkpoint() -> None:
    """Process raw events into session summaries (Stop hook)."""
    config = _load_config()
    store = _load_store(config)
    store.checkpoint()
    typer.echo("Checkpointed.")


# ── archive ───────────────────────────────────────────────────────

@app.command()
def archive() -> None:
    """Compact and deduplicate raw events (session end)."""
    config = _load_config()
    store = _load_store(config)
    store.archive()
    typer.echo("Archived.")


# ── list ──────────────────────────────────────────────────────────

@app.command(name="list")
def list_tasks(
    domain: Optional[str] = typer.Option(None, help="Filter by domain"),
    outcome: Optional[Outcome] = typer.Option(None, help="Filter by outcome"),
    category: Optional[str] = typer.Option(None, help="Filter by category (reference/trial)"),
) -> None:
    """List all tasks with optional filters."""
    config = _load_config()
    store = _load_store(config)

    tasks = store.read_all_tasks()
    if domain:
        tasks = [t for t in tasks if t.domain == domain]
    if outcome:
        tasks = [t for t in tasks if t.outcome == outcome]
    if category:
        tasks = [t for t in tasks if t.category == category]

    if not tasks:
        typer.echo("No tasks found.")
        return

    for t in tasks:
        typer.echo(
            f"{t.id} | {t.category} | {t.outcome.value} | "
            f"{t.feature} | {t.source} → {t.target} | "
            f"compile={t.quality.compile_pass} lint={t.quality.lint_errors}"
        )


if __name__ == "__main__":
    app()