"""Configuration — domain, budgets, tier defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class TierBudget(BaseModel):
    """Token budget per tier for progressive disclosure injection."""
    deterministic: int = Field(default=500, description="Tier 1 budget (always injected, full fix)")
    probabilistic: int = Field(default=1000, description="Tier 2 budget (on match, facts + fix)")
    empirical: int = Field(default=2000, description="Tier 3 budget (on demand, full example)")
    index: int = Field(default=200, description="Index budget (id + title + category only)")
    total: int = Field(default=4000, description="Total budget ceiling")


class MBMConfig(BaseModel):
    """MigBotMemory configuration."""
    domain: str = Field(default="default", description="Migration domain tag")
    mbm_dir: str = Field(default=".mbm", description="Working directory (relative to project root)")
    tier_budget: TierBudget = Field(default_factory=TierBudget)
    promote_thresholds: dict[str, float] = Field(
        default_factory=lambda: {
            "empirical_to_probabilistic": 2,   # consistent occurrences needed
            "probabilistic_to_deterministic": 3,
        },
        description="Number of consistent occurrences required for tier promotion",
    )

    @property
    def root(self) -> Path:
        """Absolute path to .mbm directory."""
        return Path(self.mbm_dir).resolve()

    @property
    def patterns_dir(self) -> Path:
        return self.root / "patterns"

    @property
    def context_dir(self) -> Path:
        return self.root / "context"

    @property
    def sessions_dir(self) -> Path:
        return self.root / "sessions"

    def resolve_path(self, relative: str) -> Path:
        """Resolve a path relative to mbm_dir."""
        return self.root / relative

    @classmethod
    def load(cls, project_root: Optional[Path] = None) -> MBMConfig:
        """Load config from project root's .mbm/config.json."""
        if project_root is None:
            project_root = Path.cwd()
        config_path = project_root / ".mbm" / "config.json"
        if config_path.exists():
            return cls.model_validate_json(config_path.read_text(encoding="utf-8"))
        return cls(mbm_dir=str(project_root / ".mbm"))

    def save(self) -> None:
        """Write config to .mbm/config.json."""
        config_path = self.root / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            self.model_dump_json(indent=2),
            encoding="utf-8",
        )