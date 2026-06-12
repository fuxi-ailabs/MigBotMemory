"""Configuration — domain, budgets, skill→phase mapping."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .models import Phase


class Budget(BaseModel):
    """Token budget for progressive disclosure injection."""
    reference_full: int = Field(default=500, description="Full injection for reference tasks")
    index: int = Field(default=300, description="Index table for all tasks")
    total: int = Field(default=4000, description="Total budget ceiling")


# Default skill→phase mapping — maps skill invocations to lifecycle phases
DEFAULT_PHASE_MAP: dict[str, Phase] = {
    "a2h-spec": Phase.task,
    "a2h-plan": Phase.plan,
    "a2h-execute": Phase.execute,
    "a2h-verify": Phase.verify,
    "hmos-fix-build-errors": Phase.execute,
    "arkts-knowledge-verifier": Phase.verify,
    "commit": Phase.commit,
}


class MBMConfig(BaseModel):
    """MigBotMemory configuration."""
    domain: str = Field(default="default", description="Migration domain tag")
    mbm_dir: str = Field(default=".mbm", description="Working directory (relative to project root)")
    budget: Budget = Field(default_factory=Budget)
    phase_map: dict[str, Phase] = Field(
        default_factory=lambda: DEFAULT_PHASE_MAP,
        description="Maps skill names to lifecycle phases for hook event classification",
    )

    @property
    def root(self) -> Path:
        return Path(self.mbm_dir).resolve()

    @property
    def tasks_dir(self) -> Path:
        return self.root / "tasks"

    @property
    def reference_dir(self) -> Path:
        return self.tasks_dir / "reference"

    @property
    def trial_dir(self) -> Path:
        return self.tasks_dir / "trial"

    @property
    def raw_dir(self) -> Path:
        return self.root / "raw"

    @property
    def context_dir(self) -> Path:
        return self.root / "context"

    @classmethod
    def load(cls, project_root: Optional[Path] = None) -> MBMConfig:
        if project_root is None:
            project_root = Path.cwd()
        config_path = project_root / ".mbm" / "config.json"
        if config_path.exists():
            return cls.model_validate_json(config_path.read_text(encoding="utf-8"))
        return cls(mbm_dir=str(project_root / ".mbm"))

    def save(self) -> None:
        config_path = self.root / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            self.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def resolve_phase(self, skill_name: str) -> Optional[Phase]:
        """Map a skill name to its lifecycle phase."""
        return self.phase_map.get(skill_name)