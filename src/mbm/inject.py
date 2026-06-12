"""Progressive disclosure — briefing generation with 3-level compression.

Injection strategy:
  - reference tasks: always inject full summaries (task→plan→execute→verify→commit)
  - trial tasks: inject only index row (feature, outcome, what went wrong)
  - full details available via mbm lookup (lossless)

Compression mapping:
  Tool level  → raw/events.jsonl (skill invocation events)
  Session level → index.json (task_id → {feature, outcome, quality})
  Task level → reference/trial/*.json (full lifecycle record)
"""

from __future__ import annotations

from typing import Optional

from .config import MBMConfig
from .models import Outcome, TaskRecord
from .store import TaskStore

TOKEN_CHARS_RATIO = 4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // TOKEN_CHARS_RATIO)


class BriefingGenerator:
    """Generate progressive disclosure briefing from task lifecycle records."""

    def __init__(self, store: TaskStore, config: MBMConfig) -> None:
        self.store = store
        self.config = config

    def generate(self, domain: Optional[str] = None) -> str:
        reference_tasks = self.store.read_reference_tasks()
        trial_tasks = self.store.read_trial_tasks()

        if domain:
            reference_tasks = [t for t in reference_tasks if t.domain == domain]
            trial_tasks = [t for t in trial_tasks if t.domain == domain]

        budget = self.config.budget
        sections = []
        total_tokens = 0

        # ── Reference tasks: full lifecycle summaries ──────────────
        ref_content = self._format_reference(reference_tasks)
        ref_tokens = estimate_tokens(ref_content)
        if ref_tokens > budget.reference_full:
            ref_content = self._trim_reference(reference_tasks, budget.reference_full)
            ref_tokens = estimate_tokens(ref_content)
        sections.append(ref_content)
        total_tokens += ref_tokens

        # ── Trial tasks: index only (what went wrong) ──────────────
        trial_content = self._format_trial_index(trial_tasks)
        trial_tokens = estimate_tokens(trial_content)
        remaining = budget.total - total_tokens
        if trial_tokens > remaining:
            trial_content = self._trim_trial_index(trial_tasks, remaining)
            trial_tokens = estimate_tokens(trial_content)
        sections.append(trial_content)
        total_tokens += trial_tokens

        header = f"## Migration Memory (domain: {domain or 'all'})"
        footer = (
            f"\n> Budget: ~{total_tokens}/{budget.total} | "
            f"ref={len(reference_tasks)} trial={len(trial_tasks)}\n"
            f"> Use `mbm lookup <task_id>` for full lifecycle details."
        )

        return header + "\n\n" + "\n\n".join(s for s in sections if s) + footer

    def generate_and_write(self, domain: Optional[str] = None) -> str:
        briefing = self.generate(domain)
        path = self.config.context_dir / "briefing.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(briefing, encoding="utf-8")
        return briefing

    # ── Formatting ────────────────────────────────────────────────

    def _format_reference(self, tasks: list[TaskRecord]) -> str:
        """Full lifecycle summaries for reference (success) tasks."""
        if not tasks:
            return "### Reference Migrations\n(none yet)"
        lines = ["### Reference Migrations (success — learn from these)"]
        for t in tasks:
            lines.append(f"**{t.id}** — {t.feature}: {t.source} → {t.target}")
            # Phase summaries — the compressed lifecycle
            for phase_name, summary in [
                ("Task", t.task_summary),
                ("Plan", t.plan_summary),
                ("Exec", t.execute_summary),
                ("Verify", t.verify_summary),
            ]:
                if summary:
                    lines.append(f"  - {phase_name}: {summary}")
            if t.key_decisions:
                lines.append(f"  - Decisions: {'; '.join(t.key_decisions)}")
            if t.key_fixes:
                lines.append(f"  - Fixes: {'; '.join(t.key_fixes)}")
        return "\n".join(lines)

    def _format_trial_index(self, tasks: list[TaskRecord]) -> str:
        """Index table for trial (partial/failed) tasks — just feature + outcome + lesson."""
        if not tasks:
            return ""
        lines = ["### Trial Migrations (partial/failed — what went wrong)"]
        lines.append("| ID | Feature | Outcome | What went wrong |")
        lines.append("|---|---|---|---|")
        for t in tasks:
            lesson = "; ".join(t.key_errors[:3]) if t.key_errors else t.verify_summary or "—"
            lines.append(
                f"| {t.id} | {t.feature} | {t.outcome.value} | {lesson} |"
            )
        return "\n".join(lines)

    # ── Budget trimming ───────────────────────────────────────────

    def _trim_reference(self, tasks: list[TaskRecord], budget: int) -> str:
        """Trim reference injection to fit budget — keep one-line summaries only."""
        lines = ["### Reference Migrations (success)"]
        current = estimate_tokens(lines[0])
        for t in tasks:
            entry = f"- **{t.id}** {t.source} → {t.target}: {t.execute_summary or t.task_summary or t.feature}"
            if current + estimate_tokens(entry) > budget:
                lines.append(f"  ... ({len(tasks)} more, use `mbm lookup`)")
                break
            lines.append(entry)
            current += estimate_tokens(entry)
        return "\n".join(lines)

    def _trim_trial_index(self, tasks: list[TaskRecord], budget: int) -> str:
        """Trim trial index to fit remaining budget."""
        lines = ["### Trial Migrations"]
        current = estimate_tokens(lines[0])
        for t in tasks:
            entry = f"- {t.id}: {t.outcome.value} — {t.key_errors[0] if t.key_errors else '—'}"
            if current + estimate_tokens(entry) > budget:
                break
            lines.append(entry)
            current += estimate_tokens(entry)
        return "\n".join(lines)