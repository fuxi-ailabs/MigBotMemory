"""Tests for lifecycle — skill event → checkpoint → briefing flow."""

from pathlib import Path

import pytest

from mbm.config import MBMConfig
from mbm.models import Outcome, Phase, QualityMetrics, SkillEvent, TaskRecord
from mbm.store import TaskStore


@pytest.fixture
def tmp_config(tmp_path: Path) -> MBMConfig:
    mbm_dir = tmp_path / ".mbm"
    config = MBMConfig(domain="lifecycle-test", mbm_dir=str(mbm_dir))
    config.save()
    return config


@pytest.fixture
def store(tmp_config: MBMConfig) -> TaskStore:
    return TaskStore(tmp_config)


class TestFullLifecycle:
    """Simulate: skill events → checkpoint → record task → archive."""

    def test_skill_events_to_task_record(self, store: TaskStore, tmp_config: MBMConfig) -> None:
        # Step 1: Skill invocations are captured by PostToolUse hook
        events = [
            SkillEvent(skill_name="a2h-spec", phase=Phase.task),
            SkillEvent(skill_name="a2h-plan", phase=Phase.plan),
            SkillEvent(skill_name="a2h-execute", phase=Phase.execute),
            SkillEvent(skill_name="a2h-verify", phase=Phase.verify),
        ]
        for evt in events:
            store.append_event(evt)

        # Step 2: Stop hook → checkpoint
        store.checkpoint()

        # Verify events were captured
        all_events = store.read_events()
        assert len(all_events) == 4

        # Step 3: LLM records the completed task
        task = TaskRecord(
            id="settings-page",
            domain="lifecycle-test",
            feature="SettingsActivity",
            source="SettingsActivity.java",
            target="SettingsPage.ets",
            task_summary="Migrate Settings with preferences storage",
            execute_summary="Converted to Column + List",
            verify_summary="Compile pass, lint clean",
            key_decisions=["Use List for preference items"],
            key_errors=["arkts-no-var in SettingsAdapter"],
            key_fixes=["Replace var with let"],
            outcome=Outcome.success,
            quality=QualityMetrics(compile_pass=True, verify_pass=True, lint_errors=0),
        )
        store.write_task(task)

        # Verify task stored as reference
        ref_tasks = store.read_reference_tasks()
        assert len(ref_tasks) == 1
        assert ref_tasks[0].id == "settings-page"

        # Step 4: Archive
        store.archive()

        # Verify deduplicated events
        events_after = store.read_events()
        assert len(events_after) <= 4

    def test_partial_failure_task(self, store: TaskStore, tmp_config: MBMConfig) -> None:
        """A partial/failed migration should go to trial category."""
        task = TaskRecord(
            id="chat-page-failed",
            domain="lifecycle-test",
            feature="ChatActivity",
            source="ChatActivity.java",
            target="ChatPage.ets",
            outcome=Outcome.partial,
            quality=QualityMetrics(compile_pass=True, verify_pass=False, lint_errors=5),
            key_errors=["15 compile errors initially", "RecyclerView adapter incompatible"],
        )
        store.write_task(task)

        trial_tasks = store.read_trial_tasks()
        assert len(trial_tasks) == 1
        assert trial_tasks[0].category == "trial"

    def test_graceful_degradation(self, tmp_path: Path) -> None:
        """Without .mbm dir, operations should handle gracefully."""
        config = MBMConfig(domain="none", mbm_dir=str(tmp_path / "nonexistent"))
        store = TaskStore(config)
        store._ensure_dirs()
        assert config.root.exists()