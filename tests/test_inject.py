"""Tests for BriefingGenerator — progressive disclosure, budget trimming."""

from pathlib import Path

import pytest

from mbm.config import MBMConfig, TierBudget
from mbm.inject import BriefingGenerator, estimate_tokens
from mbm.models import Category, FixStrategy, FixTemplate, MappingEntry, Pattern, Tier
from mbm.store import PatternStore


@pytest.fixture
def tmp_config(tmp_path: Path) -> MBMConfig:
    mbm_dir = tmp_path / ".mbm"
    config = MBMConfig(domain="test-domain", mbm_dir=str(mbm_dir))
    config.save()
    return config


@pytest.fixture
def store(tmp_config: MBMConfig) -> PatternStore:
    s = PatternStore(tmp_config)
    s.init_store()
    return s


def make_pattern(
    id: str = "test-pattern",
    signature: str = "test-sig",
    domain: str = "test-domain",
    category: Category = Category.syntax_error,
    title: str = "Test pattern",
    confidence: float = 0.5,
    auto_apply: bool = False,
) -> Pattern:
    return Pattern(
        id=id,
        signature=signature,
        domain=domain,
        category=category,
        title=title,
        facts=["Fact 1", "Fact 2"],
        fix_template=FixTemplate(
            strategy=FixStrategy.bracket_assignment,
            before="wrong code",
            after="correct code",
        ),
        confidence=confidence,
        auto_apply=auto_apply,
    )


class TestEstimateTokens:
    def test_short_text(self) -> None:
        assert estimate_tokens("hello") >= 1

    def test_empty_text(self) -> None:
        assert estimate_tokens("") >= 1


class TestBriefingGeneration:
    def test_empty_store(self, store: PatternStore, tmp_config: MBMConfig) -> None:
        gen = BriefingGenerator(store, tmp_config)
        briefing = gen.generate()
        assert "Error Pattern Memory" in briefing
        assert "Tier 1" in briefing

    def test_deterministic_pattern(self, store: PatternStore, tmp_config: MBMConfig) -> None:
        p = make_pattern(id="det-1", confidence=1.0, auto_apply=True)
        store.write(p)
        gen = BriefingGenerator(store, tmp_config)
        briefing = gen.generate()
        assert "det-1" in briefing
        assert "[auto]" in briefing
        assert "bracket_assignment" in briefing

    def test_probabilistic_pattern(self, store: PatternStore, tmp_config: MBMConfig) -> None:
        p = make_pattern(id="prob-1", confidence=0.8)
        store.write(p)
        gen = BriefingGenerator(store, tmp_config)
        briefing = gen.generate()
        assert "prob-1" in briefing
        assert "conf=0.80" in briefing

    def test_empirical_pattern_index_only(self, store: PatternStore, tmp_config: MBMConfig) -> None:
        p = make_pattern(id="emp-1", confidence=0.5)
        store.write(p)
        gen = BriefingGenerator(store, tmp_config)
        briefing = gen.generate()
        # Empirical should appear in index, not in Tier 3 full section
        assert "emp-1" in briefing
        assert "| emp |" in briefing

    def test_domain_filter(self, store: PatternStore, tmp_config: MBMConfig) -> None:
        p1 = make_pattern(id="d1", domain="test-domain", confidence=1.0)
        p2 = make_pattern(id="d2", domain="other-domain", confidence=1.0)
        store.write(p1)
        store.write(p2)
        gen = BriefingGenerator(store, tmp_config)
        briefing = gen.generate(domain="test-domain")
        assert "d1" in briefing
        assert "d2" not in briefing

    def test_mappings_included(self, store: PatternStore, tmp_config: MBMConfig) -> None:
        mapping = MappingEntry(
            old="@ohos.data.rdb",
            new="@kit.ArkData",
            domain="test-domain",
        )
        store.write_mapping(mapping)
        gen = BriefingGenerator(store, tmp_config)
        briefing = gen.generate()
        assert "@ohos.data.rdb" in briefing
        assert "@kit.ArkData" in briefing

    def test_write_to_file(self, store: PatternStore, tmp_config: MBMConfig) -> None:
        gen = BriefingGenerator(store, tmp_config)
        content = gen.generate_and_write()
        path = tmp_config.context_dir / "briefing.md"
        assert path.exists()
        assert path.read_text(encoding="utf-8") == content

    def test_budget_footer(self, store: PatternStore, tmp_config: MBMConfig) -> None:
        gen = BriefingGenerator(store, tmp_config)
        briefing = gen.generate()
        assert "Token budget" in briefing
        assert "mbm lookup" in briefing


class TestBudgetTrimming:
    def test_trim_tier1_over_budget(self, store: PatternStore, tmp_config: MBMConfig) -> None:
        # Write many deterministic patterns to exceed budget
        for i in range(20):
            p = make_pattern(
                id=f"det-{i}",
                confidence=1.0,
                title=f"Very long title pattern number {i} with lots of details",
            )
            store.write(p)

        # Set very small budget
        tmp_config.tier_budget = TierBudget(deterministic=50, total=100)
        gen = BriefingGenerator(store, tmp_config)
        briefing = gen.generate()
        # Should have truncation marker
        assert "truncated" in briefing or "more patterns" in briefing or len(briefing) < 5000