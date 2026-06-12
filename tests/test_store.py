"""Tests for TaskStore — task lifecycle CRUD, events, index, archive."""

import json
from pathlib import Path

import pytest

from mbm.config import MBMConfig
from mbm.models import Outcome, Phase, QualityMetrics, SkillEvent, TaskIndex, TaskRecord
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
    feature: str = "LoginActivity",
    source: str = "LoginActivity.java",
    target: str = "LoginPage.ets",
    outcome: Outcome = Outcome.success,
    compile_pass: bool = True,
    verify_pass: bool = True,
    lint_errors: int = 0,
) -> TaskRecord:
    return TaskRecord(
        id=id,
        domain="test-domain",
        feature=feature,
        source=source,
        target=target,
        task_summary="Migrate LoginActivity with login form and password validation",
        plan_summary="Use Column + TextInput, preserve form validation logic",
        execute_summary="Converted XML layout to Column, kept validation as separate method",
        verify_summary="Compile pass, visual match 95%",
        commit_summary="5 files committed, 3 pages + 2 helpers",
        key_decisions=["Use Column instead of LinearLayout", "Keep validation as pure function"],
        key_errors=["arkts-identifiers-as-prop-names in ValuesBucket"],
        key_fixes=["Bracket assignment: bucket['key'] = value"],
        outcome=outcome,
        quality=QualityMetrics(compile_pass=compile_pass, verify_pass=verify_pass, lint_errors=lint_errors),
    )


class TestStoreInit:
    def test_creates_dirs(self, tmp_config: MBMConfig) -> None:
        store = TaskStore(tmp_config)
        assert tmp_config.raw_dir.exists()
        assert tmp_config.reference_dir.exists()
        assert tmp_config.trial_dir.exists()
        assert tmp_config.context_dir.exists()


class TestTaskCRUD:
    def test_write_reference_task(self, store: TaskStore) -> None:
        task = make_task(outcome=Outcome.success)
        store.write_task(task)
        assert (store.config.reference_dir / "login-page.json").exists()

    def test_write_trial_task(self, store: TaskStore) -> None:
        task = make_task(id="chat-page", outcome=Outcome.partial, compile_pass=True, verify_pass=False)
        store.write_task(task)
        assert (store.config.trial_dir / "chat-page.json").exists()

    def test_read_task(self, store: TaskStore) -> None:
        task = make_task()
        store.write_task(task)
        loaded = store.read_task("login-page")
        assert loaded is not None
        assert loaded.id == "login-page"
        assert loaded.outcome == Outcome.success
        assert loaded.feature == "LoginActivity"

    def test_read_nonexistent(self, store: TaskStore) -> None:
        assert store.read_task("nonexistent") is None

    def test_read_all_tasks(self, store: TaskStore) -> None:
        t1 = make_task(id="ref-1", outcome=Outcome.success)
        t2 = make_task(id="trial-1", outcome=Outcome.failed)
        store.write_task(t1)
        store.write_task(t2)
        all_tasks = store.read_all_tasks()
        assert len(all_tasks) == 2

    def test_read_reference_tasks(self, store: TaskStore) -> None:
        t1 = make_task(id="ref-1", outcome=Outcome.success)
        t2 = make_task(id="trial-1", outcome=Outcome.failed)
        store.write_task(t1)
        store.write_task(t2)
        ref_tasks = store.read_reference_tasks()
        assert len(ref_tasks) == 1
        assert ref_tasks[0].id == "ref-1"

    def test_read_trial_tasks(self, store: TaskStore) -> None:
        t1 = make_task(id="ref-1", outcome=Outcome.success)
        t2 = make_task(id="trial-1", outcome=Outcome.failed)
        store.write_task(t1)
        store.write_task(t2)
        trial_tasks = store.read_trial_tasks()
        assert len(trial_tasks) == 1
        assert trial_tasks[0].id == "trial-1"

    def test_task_category_property(self, store: TaskStore) -> None:
        success_task = make_task(outcome=Outcome.success)
        assert success_task.category == "reference"
        failed_task = make_task(outcome=Outcome.failed)
        assert failed_task.category == "trial"

    def test_write_updates_index(self, store: TaskStore) -> None:
        task = make_task()
        store.write_task(task)
        index = store.read_index()
        assert "login-page" in index.entries


class TestEvents:
    def test_append_event(self, store: TaskStore) -> None:
        evt = SkillEvent(skill_name="a2h-spec", phase=Phase.task)
        store.append_event(evt)
        events = store.read_events()
        assert len(events) == 1
        assert events[0].skill_name == "a2h-spec"
        assert events[0].phase == Phase.task

    def test_read_empty_events(self, store: TaskStore) -> None:
        events = store.read_events()
        assert len(events) == 0

    def test_clear_events(self, store: TaskStore) -> None:
        evt = SkillEvent(skill_name="a2h-spec")
        store.append_event(evt)
        store.clear_events()
        assert len(store.read_events()) == 0


class TestPhaseMapping:
    def test_config_resolves_phase(self, tmp_config: MBMConfig) -> None:
        assert tmp_config.resolve_phase("a2h-spec") == Phase.task
        assert tmp_config.resolve_phase("a2h-plan") == Phase.plan
        assert tmp_config.resolve_phase("a2h-execute") == Phase.execute
        assert tmp_config.resolve_phase("a2h-verify") == Phase.verify
        assert tmp_config.resolve_phase("unknown-skill") is None


class TestCheckpointArchive:
    def test_checkpoint(self, store: TaskStore) -> None:
        evt = SkillEvent(skill_name="a2h-spec", phase=Phase.task)
        store.append_event(evt)
        store.checkpoint()
        checkpoint_path = store.config.raw_dir / "checkpoint.json"
        assert checkpoint_path.exists()

    def test_archive_deduplicates(self, store: TaskStore) -> None:
        # Write duplicate events
        evt1 = SkillEvent(skill_name="a2h-spec", skill_args="same-args")
        evt2 = SkillEvent(skill_name="a2h-spec", skill_args="same-args")
        store.append_event(evt1)
        store.append_event(evt2)
        store.archive()
        events = store.read_events()
        assert len(events) == 1  # deduplicated


class TestLookupByFeature:
    def test_find_by_feature_name(self, store: TaskStore) -> None:
        task = make_task(feature="LoginActivity")
        store.write_task(task)
        results = store.lookup_by_feature("Login")
        assert len(results) == 1
        assert results[0].id == "login-page"

    def test_find_no_match(self, store: TaskStore) -> None:
        results = store.lookup_by_feature("NonexistentFeature")
        assert len(results) == 0