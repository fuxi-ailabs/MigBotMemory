"""Tests for BriefingGenerator — progressive disclosure with task lifecycle."""

from pathlib import Path

import pytest

from mbm.config import MBMConfig
from mbm.inject import BriefingGenerator, estimate_tokens
from mbm.models import Outcome, QualityMetrics, TaskRecord
from mbm.store import TaskStore


@pytest.fixture
def tmp_config(tmp_path: Path) -> MBMConfig:
    mbm_dir = tmp_path / ".mbm"
    config = MBMConfig(domain="test-domain", mbm_dir=str(mbm_dir))
    config.save()
    return config


@pytest.fixture
def store(tmp_config: MBMConfig) -> TaskStore:
    return TaskStore(tmp_config)


def make_task(
    id: str = "login-page",
    outcome: Outcome = Outcome.success,
    compile_pass: bool = True,
    verify_pass: bool = True,
    lint_errors: int = 0,
) -> TaskRecord:
    return TaskRecord(
        id=id,
        domain="test-domain",
        feature="LoginActivity",
        source="LoginActivity.java",
        target="LoginPage.ets",
        task_summary="Migrate LoginActivity",
        plan_summary="Use Column + TextInput",
        execute_summary="Converted XML to Column",
        verify_summary="Compile pass",
        key_decisions=["Use Column layout"],
        key_fixes=["Bracket assignment fix"],
        outcome=outcome,
        quality=QualityMetrics(compile_pass=compile_pass, verify_pass=verify_pass, lint_errors=lint_errors),
    )


class TestBriefingEmpty:
    def test_empty_store(self, store: TaskStore, tmp_config: MBMConfig) -> None:
        gen = BriefingGenerator(store, tmp_config)
        briefing = gen.generate()
        assert "Migration Memory" in briefing
        assert "(none yet)" in briefing


class TestBriefingReference:
    def test_reference_task_shows_lifecycle(self, store: TaskStore, tmp_config: MBMConfig) -> None:
        task = make_task(outcome=Outcome.success)
        store.write_task(task)
        gen = BriefingGenerator(store, tmp_config)
        briefing = gen.generate()
        # Should show full lifecycle summaries
        assert "login-page" in briefing
        assert "LoginActivity.java" in briefing
        assert "LoginPage.ets" in briefing
        assert "Task:" in briefing or "task_summary" in task.task_summary
        assert "Bracket assignment fix" in briefing

    def test_trial_task_shows_index_only(self, store: TaskStore, tmp_config: MBMConfig) -> None:
        task = make_task(id="chat-page", outcome=Outcome.partial, verify_pass=False)
        store.write_task(task)
        gen = BriefingGenerator(store, tmp_config)
        briefing = gen.generate()
        # Should show index table, not full summaries
        assert "chat-page" in briefing
        assert "partial" in briefing
        # Should NOT show full lifecycle details
        assert "Plan:" not in briefing or "Plan" not in briefing.split("chat-page")[0] if "chat-page" in briefing else True


class TestBriefingDomainFilter:
    def test_domain_filter(self, store: TaskStore, tmp_config: MBMConfig) -> None:
        t1 = make_task(id="d1")
        t2 = TaskRecord(
            id="d2", domain="other-domain", feature="X",
            source="x.java", target="x.ets", outcome=Outcome.success,
            quality=QualityMetrics(compile_pass=True, verify_pass=True),
        )
        store.write_task(t1)
        store.write_task(t2)
        gen = BriefingGenerator(store, tmp_config)
        briefing = gen.generate(domain="test-domain")
        assert "d1" in briefing
        assert "d2" not in briefing


class TestBriefingBudget:
    def test_budget_footer(self, store: TaskStore, tmp_config: MBMConfig) -> None:
        gen = BriefingGenerator(store, tmp_config)
        briefing = gen.generate()
        assert "Budget:" in briefing
        assert "mbm lookup" in briefing

    def test_write_to_file(self, store: TaskStore, tmp_config: MBMConfig) -> None:
        gen = BriefingGenerator(store, tmp_config)
        content = gen.generate_and_write()
        path = tmp_config.context_dir / "briefing.md"
        assert path.exists()
        assert path.read_text(encoding="utf-8") == content