"""Progressive disclosure — briefing generation with token budget trimming."""

from __future__ import annotations

import re
from typing import Optional

from .config import MBMConfig
from .models import Category, MappingEntry, Pattern, Tier
from .store import PatternStore

# Rough token estimate: 1 token ≈ 4 chars for English, ≈ 2 chars for Chinese
TOKEN_CHARS_RATIO = 4


def estimate_tokens(text: str) -> int:
    """Rough token count estimation."""
    return max(1, len(text) // TOKEN_CHARS_RATIO)


class BriefingGenerator:
    """Generate progressive disclosure briefing for session context injection."""

    def __init__(self, store: PatternStore, config: MBMConfig) -> None:
        self.store = store
        self.config = config

    def generate(self, domain: Optional[str] = None) -> str:
        """Generate the full briefing markdown with tier-based progressive disclosure.

        Args:
            domain: Filter patterns by domain. None = all domains.
        """
        all_patterns = self.store.read_all()
        mappings = self.store.read_mappings()

        # Filter by domain if specified
        if domain:
            all_patterns = [p for p in all_patterns if p.domain == domain]
            mappings = [m for m in mappings if m.domain == domain]

        # Split patterns into tiers
        deterministic = [p for p in all_patterns if p.tier == Tier.deterministic]
        probabilistic = [p for p in all_patterns if p.tier == Tier.probabilistic]
        empirical = [p for p in all_patterns if p.tier == Tier.empirical]

        budget = self.config.tier_budget

        sections = []
        total_tokens = 0

        # ── Tier 1: Deterministic (always injected, full fix_template) ──
        tier1_content = self._format_tier1(deterministic)
        tier1_tokens = estimate_tokens(tier1_content)
        if tier1_tokens > budget.deterministic:
            tier1_content = self._trim_tier1(deterministic, budget.deterministic)
            tier1_tokens = estimate_tokens(tier1_content)
        sections.append(tier1_content)
        total_tokens += tier1_tokens

        # ── Mappings (always injected alongside Tier 1) ──
        if mappings:
            mappings_content = self._format_mappings(mappings)
            total_tokens += estimate_tokens(mappings_content)
            sections.append(mappings_content)

        # ── Index layer: Tier 2/3 titles only ──
        index_content = self._format_index(probabilistic, empirical)
        index_tokens = estimate_tokens(index_content)
        if total_tokens + index_tokens > budget.total:
            # Skip index if over total budget
            pass
        else:
            sections.append(index_content)
            total_tokens += index_tokens

        # ── Tier 2: Probabilistic (on match, facts + fix) ──
        tier2_content = self._format_tier2(probabilistic)
        tier2_tokens = estimate_tokens(tier2_content)
        if total_tokens + tier2_tokens > budget.total:
            # Trim to fit remaining budget
            remaining = budget.total - total_tokens
            if remaining > 50:
                tier2_content = self._trim_tier2(probabilistic, remaining)
                tier2_tokens = estimate_tokens(tier2_content)
                sections.append(tier2_content)
                total_tokens += tier2_tokens
        else:
            sections.append(tier2_content)
            total_tokens += tier2_tokens

        # ── Tier 3: Empirical (on demand, only mentioned in index) ──
        # Empirical patterns are NOT fully injected — only their index entry
        # LLM fetches details via `mbm lookup` when needed

        header = f"## Error Pattern Memory (domain: {domain or 'all'})"
        footer = (
            f"\n> Token budget: ~{total_tokens}/{budget.total} | "
            f"Tier1={len(deterministic)} Tier2={len(probabilistic)} Tier3={len(empirical)}\n"
            f"> Use `mbm lookup <signature>` to fetch full pattern details on demand."
        )

        return header + "\n\n" + "\n\n".join(sections) + footer

    def generate_and_write(self, domain: Optional[str] = None) -> str:
        """Generate briefing and write to .mbm/context/briefing.md."""
        briefing = self.generate(domain)
        path = self.config.context_dir / "briefing.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(briefing, encoding="utf-8")
        return briefing

    # ── Formatting helpers ────────────────────────────────────────

    def _format_tier1(self, patterns: list[Pattern]) -> str:
        """Full disclosure: title + facts + fix_template for deterministic patterns."""
        if not patterns:
            return "### Tier 1 — Deterministic\n(none)"
        lines = ["### Tier 1 — Deterministic (always apply)"]
        for p in patterns:
            auto_tag = " [auto]" if p.auto_apply else ""
            lines.append(
                f"- **{p.id}** [{p.category.value}]{auto_tag}: {p.title}"
            )
            for fact in p.facts:
                lines.append(f"  - {fact}")
            lines.append(f"  - Fix: `{p.fix_template.before}` → `{p.fix_template.after}`"
                         f" (strategy: {p.fix_template.strategy.value})")
        return "\n".join(lines)

    def _format_tier2(self, patterns: list[Pattern]) -> str:
        """Moderate disclosure: title + facts + fix_template for probabilistic patterns."""
        if not patterns:
            return ""
        lines = ["### Tier 2 — Probabilistic (apply on match)"]
        for p in patterns:
            lines.append(
                f"- **{p.id}** [{p.category.value}] (conf={p.confidence:.2f}): {p.title}"
            )
            for fact in p.facts:
                lines.append(f"  - {fact}")
            lines.append(f"  - Fix: `{p.fix_template.before}` → `{p.fix_template.after}`"
                         f" (strategy: {p.fix_template.strategy.value})")
        return "\n".join(lines)

    def _format_index(self, probabilistic: list[Pattern], empirical: list[Pattern]) -> str:
        """Minimal disclosure: just id + title + category for Tier 2/3."""
        entries = []
        for p in probabilistic:
            entries.append(f"| {p.id} | {p.category.value} | {p.title} | prob |")
        for p in empirical:
            entries.append(f"| {p.id} | {p.category.value} | {p.title} | emp |")
        if not entries:
            return ""
        lines = ["### Available Patterns (index)", "| ID | Category | Title | Tier |", "|---|---|---|---|"]
        lines.extend(entries)
        return "\n".join(lines)

    def _format_mappings(self, mappings: list[MappingEntry]) -> str:
        """Format import/API replacement mappings."""
        if not mappings:
            return ""
        lines = ["### Import/API Mappings (always apply)"]
        for m in mappings:
            lines.append(f"- `{m.old}` → `{m.new}`")
        return "\n".join(lines)

    # ── Budget trimming ───────────────────────────────────────────

    def _trim_tier1(self, patterns: list[Pattern], budget: int) -> str:
        """Trim Tier 1 to fit budget — keep title + fix_template only, drop facts."""
        lines = ["### Tier 1 — Deterministic (always apply)"]
        current_tokens = estimate_tokens(lines[0])
        for p in patterns:
            entry = f"- **{p.id}** [{p.category.value}]: {p.title} → `{p.fix_template.after}`"
            entry_tokens = estimate_tokens(entry)
            if current_tokens + entry_tokens > budget:
                lines.append(f"  ... ({len(patterns) - patterns.index(p)} more patterns truncated)")
                break
            lines.append(entry)
            current_tokens += entry_tokens
        return "\n".join(lines)

    def _trim_tier2(self, patterns: list[Pattern], budget: int) -> str:
        """Trim Tier 2 to fit remaining budget — keep title + category only."""
        lines = ["### Tier 2 — Probabilistic (apply on match)"]
        current_tokens = estimate_tokens(lines[0])
        for p in patterns:
            entry = f"- **{p.id}** [{p.category.value}]: {p.title}"
            entry_tokens = estimate_tokens(entry)
            if current_tokens + entry_tokens > budget:
                break
            lines.append(entry)
            current_tokens += entry_tokens
        return "\n".join(lines)