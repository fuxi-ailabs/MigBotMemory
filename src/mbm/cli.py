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
from .models import Category, FixStrategy, FixTemplate, Pattern, Tier
from .store import PatternStore

app = typer.Typer(
    name="mbm",
    help="MigBotMemory — universal compilation error pattern cache",
    no_args_is_help=True,
)


def _load_config() -> MBMConfig:
    """Load config from current working directory."""
    return MBMConfig.load(Path.cwd())


def _load_store(config: MBMConfig) -> PatternStore:
    """Load store with the given config."""
    return PatternStore(config)


# ── init ──────────────────────────────────────────────────────────

@app.command()
def init(
    domain: str = typer.Option("default", help="Migration domain tag"),
    mbm_dir: str = typer.Option(".mbm", help="Working directory (relative to project root)"),
) -> None:
    """Initialize .mbm directory structure and config."""
    config = MBMConfig(domain=domain, mbm_dir=str(Path.cwd() / mbm_dir))
    config.save()
    store = PatternStore(config)
    store.init_store()
    typer.echo(f"Initialized MigBotMemory at {config.root} (domain: {domain})")


# ── briefing ──────────────────────────────────────────────────────

@app.command()
def briefing(
    domain: Optional[str] = typer.Option(None, help="Filter patterns by domain"),
    write: bool = typer.Option(False, "--write", help="Write briefing.md to .mbm/context/"),
) -> None:
    """Generate progressive disclosure briefing for session context injection."""
    config = _load_config()
    store = _load_store(config)
    generator = BriefingGenerator(store, config)

    if write:
        content = generator.generate_and_write(domain)
        typer.echo(f"Briefing written to {config.context_dir / 'briefing.md'}")
    else:
        content = generator.generate(domain)
        typer.echo(content)


# ── write ─────────────────────────────────────────────────────────

@app.command()
def write_pattern(
    signature: str = typer.Option(..., help="Regex pattern for matching errors"),
    domain: str = typer.Option("default", help="Migration domain"),
    category: Category = typer.Option(..., help="Error category"),
    title: str = typer.Option(..., help="Short description"),
    facts: Optional[str] = typer.Option(None, help="JSON array of fact strings"),
    fix_strategy: FixStrategy = typer.Option(..., help="Fix strategy"),
    fix_before: str = typer.Option(..., help="Wrong code example"),
    fix_after: str = typer.Option(..., help="Correct code example"),
    fix_description: Optional[str] = typer.Option(None, help="Optional fix explanation"),
    confidence: float = typer.Option(0.5, help="Pattern confidence (0.5=empirical, 0.7=probabilistic, 1.0=deterministic)"),
    auto_apply: bool = typer.Option(False, help="Whether to auto-apply"),
    occurrences: int = typer.Option(1, help="Number of times observed"),
) -> None:
    """Write a new pattern to the appropriate tier."""
    config = _load_config()
    store = _load_store(config)

    # Generate pattern ID from signature + domain
    import re as regex
    id_slug = regex.sub(r"[^a-zA-Z0-9]", "-", signature.lower())[:40]
    pattern_id = f"{domain}-{id_slug}"

    facts_list = json.loads(facts) if facts else []

    pattern = Pattern(
        id=pattern_id,
        signature=signature,
        domain=domain,
        category=category,
        title=title,
        facts=facts_list,
        fix_template=FixTemplate(
            strategy=fix_strategy,
            before=fix_before,
            after=fix_after,
            description=fix_description,
        ),
        confidence=confidence,
        occurrences=occurrences,
        auto_apply=auto_apply,
    )

    store.write(pattern)
    tier_name = pattern.tier.value
    typer.echo(f"Pattern written: {pattern_id} → {tier_name} (confidence={confidence})")


# ── promote ───────────────────────────────────────────────────────

@app.command()
def promote(
    pattern_id: str = typer.Argument(help="Pattern ID to promote"),
) -> None:
    """Promote a pattern to the next tier (empirical→probabilistic→deterministic)."""
    config = _load_config()
    store = _load_store(config)

    promoted = store.promote(pattern_id)
    if promoted is None:
        typer.echo(f"Pattern not found: {pattern_id}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Promoted: {pattern_id} → {promoted.tier.value} (confidence={promoted.confidence})")


# ── lookup ────────────────────────────────────────────────────────

@app.command()
def lookup(
    signature: str = typer.Argument(help="Error signature or text to search"),
) -> None:
    """Lookup pattern details by signature (LLM on-demand retrieval)."""
    config = _load_config()
    store = _load_store(config)

    # Try exact index lookup first
    pattern = store.lookup(signature)
    if pattern is None:
        # Try matching against error text
        matches = store.lookup_by_error_text(signature)
        if matches:
            pattern = matches[0]
        else:
            typer.echo(f"No pattern found matching: {signature}", err=True)
            raise typer.Exit(1)

    # Output full pattern details (lossless disclosure)
    typer.echo(pattern.model_dump_json(indent=2))


# ── checkpoint ────────────────────────────────────────────────────

@app.command()
def checkpoint() -> None:
    """Persist session state (Stop hook)."""
    config = _load_config()
    store = _load_store(config)
    store.checkpoint()
    typer.echo("Session checkpointed.")


# ── archive ───────────────────────────────────────────────────────

@app.command()
def archive() -> None:
    """Compact and clean up pattern store (SessionEnd hook)."""
    config = _load_config()
    store = _load_store(config)
    store.archive()
    typer.echo("Store archived and compacted.")


# ── list ──────────────────────────────────────────────────────────

@app.command(name="list")
def list_patterns(
    tier: Optional[Tier] = typer.Option(None, help="Filter by tier"),
    domain: Optional[str] = typer.Option(None, help="Filter by domain"),
    category: Optional[Category] = typer.Option(None, help="Filter by category"),
) -> None:
    """List all patterns with optional filters."""
    config = _load_config()
    store = _load_store(config)

    patterns = store.read_all()
    if tier:
        patterns = [p for p in patterns if p.tier == tier]
    if domain:
        patterns = [p for p in patterns if p.domain == domain]
    if category:
        patterns = [p for p in patterns if p.category == category]

    if not patterns:
        typer.echo("No patterns found.")
        return

    for p in patterns:
        typer.echo(
            f"{p.id} | {p.tier.value} | {p.category.value} | "
            f"conf={p.confidence:.2f} | occ={p.occurrences} | {p.title}"
        )


if __name__ == "__main__":
    app()