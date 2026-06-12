"""Pattern store — JSON file CRUD + index + promotion + atomic writes."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Optional

from .config import MBMConfig
from .models import Category, FixTemplate, FixStrategy, IndexEntry, MappingEntry, Pattern, PatternIndex, Tier


class PatternStore:
    """File-based pattern storage with atomic writes and tier promotion."""

    def __init__(self, config: MBMConfig) -> None:
        self.config = config
        self._ensure_dirs()

    # ── Directory initialization ──────────────────────────────────

    def _ensure_dirs(self) -> None:
        """Create .mbm directory structure if absent."""
        for d in (self.config.patterns_dir, self.config.context_dir, self.config.sessions_dir):
            d.mkdir(parents=True, exist_ok=True)

    def init_store(self, seed_patterns: Optional[list[Pattern]] = None) -> None:
        """Initialize empty store files and optionally seed deterministic patterns."""
        for name in ("deterministic.json", "probabilistic.json"):
            path = self.config.patterns_dir / name
            if not path.exists():
                self._atomic_write_json(path, [])

        empirical_path = self.config.patterns_dir / "empirical.jsonl"
        if not empirical_path.exists():
            empirical_path.write_text("", encoding="utf-8")

        mappings_path = self.config.patterns_dir / "mappings.json"
        if not mappings_path.exists():
            self._atomic_write_json(mappings_path, [])

        index_path = self.config.patterns_dir / "index.json"
        if not index_path.exists():
            self._atomic_write_json(
                index_path,
                PatternIndex().model_dump(mode="json"),
            )

        # Seed patterns if provided
        if seed_patterns:
            for p in seed_patterns:
                self.write(p)

    # ── Atomic write ──────────────────────────────────────────────

    def _atomic_write_json(self, path: Path, data: object) -> None:
        """Write JSON with atomic .tmp → rename strategy."""
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        tmp_path.replace(path)

    def _atomic_append_jsonl(self, path: Path, pattern: Pattern) -> None:
        """Append a single JSON line to JSONL file."""
        line = pattern.model_dump_json() + "\n"
        # For JSONL, atomicity is less critical (append-only), just write directly
        path.write_text(
            path.read_text(encoding="utf-8") + line,
            encoding="utf-8",
        )

    # ── Read operations ───────────────────────────────────────────

    def _read_tier(self, tier: Tier) -> list[Pattern]:
        """Read all patterns from a tier file."""
        if tier == Tier.empirical:
            return self._read_empirical()
        filename = f"{tier.value}.json"
        path = self.config.patterns_dir / filename
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [Pattern.model_validate(p) for p in data]

    def _read_empirical(self) -> list[Pattern]:
        """Read all patterns from empirical.jsonl (append-only)."""
        path = self.config.patterns_dir / "empirical.jsonl"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        patterns = []
        for line in lines:
            if line.strip():
                try:
                    patterns.append(Pattern.model_validate_json(line))
                except Exception:
                    continue  # skip malformed lines
        return patterns

    def read_all(self) -> list[Pattern]:
        """Read all patterns across all tiers."""
        result = []
        for tier in (Tier.deterministic, Tier.probabilistic, Tier.empirical):
            result.extend(self._read_tier(tier))
        return result

    def read_mappings(self) -> list[MappingEntry]:
        """Read import/API replacement mappings."""
        path = self.config.patterns_dir / "mappings.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [MappingEntry.model_validate(m) for m in data]

    def read_index(self) -> PatternIndex:
        """Read the cross-tier index."""
        path = self.config.patterns_dir / "index.json"
        if not path.exists():
            return PatternIndex()
        data = json.loads(path.read_text(encoding="utf-8"))
        return PatternIndex.model_validate(data)

    # ── Write operations ──────────────────────────────────────────

    def write(self, pattern: Pattern) -> None:
        """Write a pattern to the appropriate tier file and update index."""
        tier = pattern.tier
        if tier == Tier.empirical:
            self._atomic_append_jsonl(
                self.config.patterns_dir / "empirical.jsonl",
                pattern,
            )
        else:
            patterns = self._read_tier(tier)
            # Replace if exists, else append
            existing_idx = next(
                (i for i, p in enumerate(patterns) if p.id == pattern.id),
                None,
            )
            if existing_idx is not None:
                patterns[existing_idx] = pattern
            else:
                patterns.append(pattern)
            self._atomic_write_json(
                self.config.patterns_dir / f"{tier.value}.json",
                [p.model_dump(mode="json") for p in patterns],
            )

        # Update index
        index = self.read_index()
        index.upsert(pattern.signature, tier, pattern.id)
        self._atomic_write_json(
            self.config.patterns_dir / "index.json",
            index.model_dump(mode="json"),
        )

    def write_mapping(self, mapping: MappingEntry) -> None:
        """Write a replacement mapping."""
        mappings = self.read_mappings()
        # Replace if old key exists, else append
        existing_idx = next(
            (i for i, m in enumerate(mappings) if m.old == mapping.old and m.domain == mapping.domain),
            None,
        )
        if existing_idx is not None:
            mappings[existing_idx] = mapping
        else:
            mappings.append(mapping)
        self._atomic_write_json(
            self.config.patterns_dir / "mappings.json",
            [m.model_dump(mode="json") for m in mappings],
        )

    # ── Lookup ────────────────────────────────────────────────────

    def lookup(self, signature: str) -> Optional[Pattern]:
        """Find a pattern by its signature regex."""
        # First check index for exact match
        index = self.read_index()
        entry = index.lookup(signature)
        if entry:
            patterns = self._read_tier(entry.tier)
            return next((p for p in patterns if p.id == entry.pattern_id), None)

        # Fall back to regex matching across all tiers
        for pattern in self.read_all():
            try:
                if re.search(pattern.signature, signature, re.IGNORECASE):
                    return pattern
            except re.error:
                continue

        return None

    def lookup_by_error_text(self, error_text: str) -> list[Pattern]:
        """Find all patterns whose signature regex matches the given error text."""
        matches = []
        for pattern in self.read_all():
            try:
                if re.search(pattern.signature, error_text, re.IGNORECASE):
                    matches.append(pattern)
            except re.error:
                continue
        return matches

    # ── Promotion lifecycle ───────────────────────────────────────

    def promote(self, pattern_id: str) -> Optional[Pattern]:
        """Promote a pattern to the next tier."""
        # Find the pattern across all tiers
        current_pattern = None
        current_tier = None
        for tier in (Tier.deterministic, Tier.probabilistic, Tier.empirical):
            patterns = self._read_tier(tier)
            found = next((p for p in patterns if p.id == pattern_id), None)
            if found:
                current_pattern = found
                current_tier = tier
                break

        if current_pattern is None:
            return None

        # Already at top tier
        if current_pattern.confidence >= 1.0:
            return current_pattern

        # Promote
        promoted = current_pattern.promote()
        new_tier = promoted.tier

        # Remove from old tier
        if current_tier == Tier.empirical:
            self._remove_from_empirical(pattern_id)
        else:
            old_patterns = self._read_tier(current_tier)
            old_patterns = [p for p in old_patterns if p.id != pattern_id]
            self._atomic_write_json(
                self.config.patterns_dir / f"{current_tier.value}.json",
                [p.model_dump(mode="json") for p in old_patterns],
            )

        # Write to new tier
        self.write(promoted)
        return promoted

    def demote(self, pattern_id: str) -> Optional[Pattern]:
        """Demote a pattern back to empirical (inconsistent fix detected)."""
        current_pattern = None
        current_tier = None
        for tier in (Tier.deterministic, Tier.probabilistic):
            patterns = self._read_tier(tier)
            found = next((p for p in patterns if p.id == pattern_id), None)
            if found:
                current_pattern = found
                current_tier = tier
                break

        if current_pattern is None:
            return None

        demoted = current_pattern.demote()

        # Remove from old tier
        old_patterns = self._read_tier(current_tier)
        old_patterns = [p for p in old_patterns if p.id != pattern_id]
        self._atomic_write_json(
            self.config.patterns_dir / f"{current_tier.value}.json",
            [p.model_dump(mode="json") for p in old_patterns],
        )

        # Write to empirical
        self.write(demoted)
        return demoted

    def _remove_from_empirical(self, pattern_id: str) -> None:
        """Remove a pattern from empirical.jsonl by rewriting the file."""
        patterns = self._read_empirical()
        patterns = [p for p in patterns if p.id != pattern_id]
        path = self.config.patterns_dir / "empirical.jsonl"
        content = "".join(p.model_dump_json() + "\n" for p in patterns)
        path.write_text(content, encoding="utf-8")

    # ── Checkpoint (Stop hook) ────────────────────────────────────

    def checkpoint(self, pending: Optional[list[Pattern]] = None) -> None:
        """Persist session state (pending patterns from current session)."""
        if pending:
            for p in pending:
                self.write(p)
        # Write session timestamp
        import datetime
        session_path = self.config.sessions_dir / "latest.json"
        self._atomic_write_json(session_path, {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "pending_count": len(pending) if pending else 0,
        })

    # ── Archive (SessionEnd hook) ─────────────────────────────────

    def archive(self) -> None:
        """Compact empirical.jsonl by deduplicating and removing stale entries."""
        patterns = self._read_empirical()
        # Deduplicate by id
        seen_ids: set[str] = set()
        deduped = []
        for p in patterns:
            if p.id not in seen_ids:
                seen_ids.add(p.id)
                deduped.append(p)

        # Rewrite empirical.jsonl
        path = self.config.patterns_dir / "empirical.jsonl"
        content = "".join(p.model_dump_json() + "\n" for p in deduped)
        path.write_text(content, encoding="utf-8")