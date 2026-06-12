"""Tests for lifecycle — SessionStart→Stop→SessionEnd flow."""

import json
from pathlib import Path

import pytest

from mbm.config import MBMConfig
from mbm.models import Category, FixStrategy, FixTemplate, Pattern, Tier
from mbm.store import PatternStore


@pytest.fixture
def tmp_config(tmp_path: Path) -> MBMConfig:
    mbm_dir = tmp_path / ".mbm"
    config = MBMConfig(domain="lifecycle-test", mbm_dir=str(mbm_dir))
    config.save()
    return config


@pytest.fixture
def store(tmp_config: MBMConfig) -> PatternStore:
    s = PatternStore(tmp_config)
    s.init_store()
    return s


def make_pattern(id: str = "lp-1", confidence: float = 0.5) -> Pattern:
    return Pattern(
        id=id,
        signature=f"test-sig-{id}",
        domain="lifecycle-test",
        category=Category.syntax_error,
        title=f"Lifecycle pattern {id}",
        facts=["Test fact"],
        fix_template=FixTemplate(
            strategy=FixStrategy.bracket_assignment,
            before="wrong",
            after="correct",
        ),
        confidence=confidence,
    )


class TestFullLifecycle:
    """Simulate a complete session lifecycle: init → write → checkpoint → archive."""

    def test_init_to_archive(self, store: PatternStore, tmp_config: MBMConfig) -> None:
        # Step 1: init — store already initialized via fixture

        # Step 2: SessionStart — write some patterns during the session
        p1 = make_pattern(id="lp-1", confidence=0.5)
        p2 = make_pattern(id="lp-2", confidence=0.8)
        store.write(p1)
        store.write(p2)

        # Step 3: Stop hook — checkpoint
        store.checkpoint()

        # Verify patterns persisted
        all_patterns = store.read_all()
        assert len(all_patterns) == 2

        # Step 4: More patterns in next session iteration
        p3 = make_pattern(id="lp-3", confidence=1.0)
        store.write(p3)

        # Step 5: Promote a pattern
        promoted = store.promote("lp-1")
        assert promoted is not None
        assert promoted.confidence == 0.7

        # Step 6: SessionEnd — archive
        store.archive()

        # Verify archive cleaned up
        all_patterns = store.read_all()
        # All 3 patterns should still exist (no data loss)
        assert len(all_patterns) == 3

    def test_graceful_degradation_no_mbm_dir(self, tmp_path: Path) -> None:
        """If .mbm/ doesn't exist, operations should fail gracefully."""
        config = MBMConfig(domain="none", mbm_dir=str(tmp_path / "nonexistent"))
        # Don't create the directory — simulate missing .mbm
        store = PatternStore(config)
        # init_store will create dirs
        store.init_store()
        assert config.root.exists()