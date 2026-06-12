"""Data models — Task lifecycle as the memory unit.

Memory unit = a feature's complete migration cycle:
  task → plan → execute → verify → commit

Compression levels:
  - Tool: compress tool outputs into structured data
  - Session: split by phase boundaries, summarize each phase, build index
  - Task: compress full lifecycle into concise record (~200 tokens)

Quality-based categorization (no confidence scores):
  - reference: outcome=success → always injected
  - trial: outcome=partial/failed → on lookup
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


# ── Lifecycle phases ─────────────────────────────────────────────

class Phase(str, enum.Enum):
    """Feature migration lifecycle phases."""
    task = "task"        # 功能定义：what to migrate
    plan = "plan"        # 设计：migration approach, spec
    execute = "execute"  # 实现：code generation, conversion
    verify = "verify"    # 测试：compile, lint, visual, functional
    commit = "commit"    # 提交：finalize, update state


# ── Outcome & quality ────────────────────────────────────────────

class Outcome(str, enum.Enum):
    """Task completion outcome."""
    success = "success"    # compile pass, verify pass
    partial = "partial"    # compile pass, some issues remain
    failed = "failed"      # compile fail or critical issues


class QualityMetrics(BaseModel):
    """Task completion quality — the real measure, not confidence."""
    compile_pass: bool = False
    lint_errors: int = 0
    lint_warnings: int = 0
    test_pass: bool = False
    verify_pass: bool = False

    def overall_ok(self) -> bool:
        """Is this a reference-quality task?"""
        return self.compile_pass and self.verify_pass and self.lint_errors == 0


# ── Error category ───────────────────────────────────────────────

class ErrorCategory(str, enum.Enum):
    """Error classification for key_errors field."""
    syntax_error = "syntax_error"
    type_mismatch = "type_mismatch"
    missing_import = "missing_import"
    api_incompatibility = "api_incompatibility"
    missing_declaration = "missing_declaration"
    duplicate_identifier = "duplicate_identifier"


# ── Core models ──────────────────────────────────────────────────

class TaskRecord(BaseModel):
    """A complete feature migration lifecycle — the memory unit.

    Three compression layers in one record:
    - summaries (task/plan/execute/verify/commit): ~50 tokens each → session level
    - key_decisions/errors/fixes: concise lists → task level
    - full record preserved in JSON file → lossless, on lookup
    """
    id: str = Field(description="Task identifier, e.g. 'login-page-migration'")
    domain: str = Field(description="Migration domain, e.g. 'android-to-harmonyos'")
    feature: str = Field(description="What was migrated, e.g. 'LoginActivity'")
    source: str = Field(description="Source file/component")
    target: str = Field(description="Target file/component")

    # ── Phase summaries (session compression: split + summarize) ──
    task_summary: str = Field(
        default="", description="What was defined (~50 tokens)",
    )
    plan_summary: str = Field(
        default="", description="Design decisions (~50 tokens)",
    )
    execute_summary: str = Field(
        default="", description="Implementation approach (~50 tokens)",
    )
    verify_summary: str = Field(
        default="", description="Test/verification results (~50 tokens)",
    )
    commit_summary: str = Field(
        default="", description="What was committed (~30 tokens)",
    )

    # ── Key artifacts (task compression: the reusable knowledge) ──
    key_decisions: list[str] = Field(
        default_factory=list,
        description="Important decisions made during migration",
    )
    key_errors: list[str] = Field(
        default_factory=list,
        description="Significant errors encountered (with category)",
    )
    key_fixes: list[str] = Field(
        default_factory=list,
        description="How errors were fixed",
    )

    # ── Outcome & quality ──
    outcome: Outcome = Outcome.failed
    quality: QualityMetrics = Field(default_factory=QualityMetrics)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    @property
    def category(self) -> str:
        """Quality-based categorization: reference or trial."""
        if self.outcome == Outcome.success and self.quality.overall_ok():
            return "reference"
        return "trial"


# ── Skill invocation event (tool compression layer) ──────────────

class SkillEvent(BaseModel):
    """A skill invocation captured by PostToolUse hook — the raw input for compression."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    skill_name: str = Field(description="Which skill was invoked, e.g. 'a2h-execute'")
    skill_args: Optional[str] = Field(default=None, description="Arguments passed to the skill")
    phase: Optional[Phase] = Field(
        default=None, description="Lifecycle phase this skill maps to",
    )
    output_summary: Optional[str] = Field(
        default=None, description="Compressed output of the skill invocation",
    )


# ── Index (session compression: index layer) ─────────────────────

class TaskIndex(BaseModel):
    """Index for fast lookup: task_id → {feature, outcome, quality_snapshot}."""
    entries: dict[str, dict] = Field(default_factory=dict)

    def upsert(self, task_id: str, feature: str, outcome: Outcome, quality: QualityMetrics) -> None:
        self.entries[task_id] = {
            "feature": feature,
            "outcome": outcome.value,
            "compile_pass": quality.compile_pass,
            "verify_pass": quality.verify_pass,
            "lint_errors": quality.lint_errors,
        }

    def remove(self, task_id: str) -> None:
        self.entries.pop(task_id, None)

    def list_reference(self) -> list[dict]:
        """List all reference-quality tasks."""
        return [
            {"id": k, **v}
            for k, v in self.entries.items()
            if v.get("outcome") == Outcome.success.value
        ]

    def list_trial(self) -> list[dict]:
        """List all trial (partial/failed) tasks."""
        return [
            {"id": k, **v}
            for k, v in self.entries.items()
            if v.get("outcome") != Outcome.success.value
        ]