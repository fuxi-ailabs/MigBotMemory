"""Pattern data models — the core domain objects."""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class Category(str, enum.Enum):
    """Error pattern classification."""
    syntax_error = "syntax_error"
    type_mismatch = "type_mismatch"
    missing_import = "missing_import"
    api_incompatibility = "api_incompatibility"
    missing_declaration = "missing_declaration"
    duplicate_identifier = "duplicate_identifier"


class Tier(str, enum.Enum):
    """Progressive disclosure tier."""
    deterministic = "deterministic"
    probabilistic = "probabilistic"
    empirical = "empirical"


class FixStrategy(str, enum.Enum):
    """Fix template strategy."""
    bracket_assignment = "bracket_assignment"
    regex_replace = "regex_replace"
    import_replacement = "import_replacement"
    explicit_cast = "explicit_cast"
    add_declaration = "add_declaration"
    rename_identifier = "rename_identifier"


class FixTemplate(BaseModel):
    """Lossless fix information — preserved fully, disclosed progressively."""
    strategy: FixStrategy
    before: str = Field(description="Wrong code example")
    after: str = Field(description="Correct code example")
    description: Optional[str] = Field(
        default=None,
        description="Optional human-readable explanation of the fix logic",
    )


class Pattern(BaseModel):
    """A single error pattern with lossless compression structure.

    Three information density layers:
    - title  (~15 tokens) → used in index layer
    - facts  (~50 tokens) → used in Tier 2 injection
    - fix_template (complete) → full disclosure in Tier 1, on-demand in Tier 2/3
    """
    id: str = Field(description="Unique pattern identifier, e.g. 'arkts-valuesbucket-bracket'")
    signature: str = Field(
        description="Regex pattern for matching this error in build output",
    )
    domain: str = Field(
        description="Migration domain, e.g. 'android-to-harmonyos'",
    )
    category: Category
    title: str = Field(description="Short human-readable description, 5-15 tokens")
    facts: list[str] = Field(
        default_factory=list,
        description="Concise standalone statements, no pronouns, include specific values. ~50 tokens total.",
    )
    fix_template: FixTemplate
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Pattern confidence: 0.5=empirical, 0.7=probabilistic, 1.0=deterministic",
    )
    occurrences: int = Field(default=1, ge=1, description="Number of times this pattern was observed")
    auto_apply: bool = Field(default=False, description="Whether to auto-apply this fix without LLM reasoning")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def tier(self) -> Tier:
        """Derive tier from confidence."""
        if self.confidence >= 1.0:
            return Tier.deterministic
        if self.confidence >= 0.7:
            return Tier.probabilistic
        return Tier.empirical

    def promote(self) -> Pattern:
        """Promote pattern: empirical→probabilistic→deterministic."""
        if self.confidence < 0.7:
            new_confidence = 0.7
            new_auto_apply = False
        elif self.confidence < 1.0:
            new_confidence = 1.0
            new_auto_apply = True
        else:
            return self  # already at top tier
        return self.model_copy(update={
            "confidence": new_confidence,
            "auto_apply": new_auto_apply,
            "occurrences": self.occurrences + 1,
            "last_seen_at": datetime.now(timezone.utc),
        })

    def demote(self) -> Pattern:
        """Demote pattern back to empirical (inconsistent fix detected)."""
        return self.model_copy(update={
            "confidence": 0.5,
            "auto_apply": False,
            "occurrences": 1,
            "last_seen_at": datetime.now(timezone.utc),
        })


class MappingEntry(BaseModel):
    """An import/API replacement mapping."""
    old: str = Field(description="Original import/API, e.g. '@ohos.data.rdb'")
    new: str = Field(description="Replacement import/API, e.g. '@kit.ArkData'")
    domain: str
    strategy: FixStrategy = FixStrategy.import_replacement


class IndexEntry(BaseModel):
    """A single entry in the pattern index."""
    tier: Tier
    pattern_id: str


class PatternIndex(BaseModel):
    """Cross-tier index: signature → IndexEntry for fast lookup."""
    entries: dict[str, IndexEntry] = Field(default_factory=dict)

    def lookup(self, signature: str) -> Optional[IndexEntry]:
        """Find which tier and pattern_id a signature maps to."""
        return self.entries.get(signature)

    def upsert(self, signature: str, tier: Tier, pattern_id: str) -> None:
        """Add or update an index entry."""
        self.entries[signature] = IndexEntry(tier=tier, pattern_id=pattern_id)

    def remove(self, signature: str) -> None:
        """Remove an index entry."""
        self.entries.pop(signature, None)