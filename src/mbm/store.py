"""Pattern store — Task lifecycle storage with 3-level compression.

Storage structure:
  raw/events.jsonl        → tool compression layer (skill invocation events)
  tasks/index.json         → session compression layer (index for fast lookup)
  tasks/reference/*.json   → reference tasks (always injectable)
  tasks/trial/*.json       → trial tasks (on lookup)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import MBMConfig
from .models import Outcome, Phase, QualityMetrics, SkillEvent, TaskIndex, TaskRecord


class TaskStore:
    """File-based task lifecycle storage with atomic writes."""

    def __init__(self, config: MBMConfig) -> None:
        self.config = config
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        for d in (
            self.config.raw_dir,
            self.config.reference_dir,
            self.config.trial_dir,
            self.config.context_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    # ── Atomic write ──────────────────────────────────────────────

    def _atomic_write_json(self, path: Path, data: object) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(path)

    # ── Tool compression: raw events ──────────────────────────────

    def append_event(self, event: SkillEvent) -> None:
        """Append a skill invocation event to raw/events.jsonl."""
        path = self.config.raw_dir / "events.jsonl"
        line = event.model_dump_json() + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)

    def read_events(self) -> list[SkillEvent]:
        """Read all raw events."""
        path = self.config.raw_dir / "events.jsonl"
        if not path.exists():
            return []
        events = []
        for line in path.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                try:
                    events.append(SkillEvent.model_validate_json(line))
                except Exception:
                    continue
        return events

    def clear_events(self) -> None:
        """Clear raw events after processing."""
        path = self.config.raw_dir / "events.jsonl"
        if path.exists():
            path.write_text("", encoding="utf-8")

    # ── Task CRUD ─────────────────────────────────────────────────

    def write_task(self, task: TaskRecord) -> None:
        """Write a task record to the appropriate category directory."""
        # Determine category
        category = task.category  # "reference" or "trial"
        target_dir = self.config.reference_dir if category == "reference" else self.config.trial_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{task.id}.json"

        # If task was previously in a different category, remove old file
        self._remove_task_file(task.id)

        self._atomic_write_json(path, task.model_dump(mode="json"))

        # Update index
        index = self.read_index()
        index.upsert(task.id, task.feature, task.outcome, task.quality)
        self._atomic_write_json(
            self.config.tasks_dir / "index.json",
            index.model_dump(mode="json"),
        )

    def _remove_task_file(self, task_id: str) -> None:
        """Remove task file from whichever category directory it's in."""
        for dir_path in (self.config.reference_dir, self.config.trial_dir):
            path = dir_path / f"{task_id}.json"
            if path.exists():
                path.unlink()

    def read_task(self, task_id: str) -> Optional[TaskRecord]:
        """Read a task record by ID, searching both categories."""
        for dir_path in (self.config.reference_dir, self.config.trial_dir):
            path = dir_path / f"{task_id}.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                return TaskRecord.model_validate(data)
        return None

    def read_all_tasks(self) -> list[TaskRecord]:
        """Read all task records from both categories."""
        tasks = []
        for dir_path in (self.config.reference_dir, self.config.trial_dir):
            if not dir_path.exists():
                continue
            for path in dir_path.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    tasks.append(TaskRecord.model_validate(data))
                except Exception:
                    continue
        return tasks

    def read_reference_tasks(self) -> list[TaskRecord]:
        """Read only reference (success) tasks."""
        tasks = []
        if not self.config.reference_dir.exists():
            return tasks
        for path in self.config.reference_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                tasks.append(TaskRecord.model_validate(data))
            except Exception:
                continue
        return tasks

    def read_trial_tasks(self) -> list[TaskRecord]:
        """Read only trial (partial/failed) tasks."""
        tasks = []
        if not self.config.trial_dir.exists():
            return tasks
        for path in self.config.trial_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                tasks.append(TaskRecord.model_validate(data))
            except Exception:
                continue
        return tasks

    # ── Index (session compression) ──────────────────────────────

    def read_index(self) -> TaskIndex:
        """Read the cross-category task index."""
        path = self.config.tasks_dir / "index.json"
        if not path.exists():
            return TaskIndex()
        data = json.loads(path.read_text(encoding="utf-8"))
        return TaskIndex.model_validate(data)

    # ── Lookup (search by feature, source, errors) ───────────────

    def lookup_by_feature(self, feature: str, domain: Optional[str] = None) -> list[TaskRecord]:
        """Find tasks that migrated a similar feature."""
        tasks = self.read_all_tasks()
        if domain:
            tasks = [t for t in tasks if t.domain == domain]
        return [
            t for t in tasks
            if feature.lower() in t.feature.lower() or feature.lower() in t.source.lower()
        ]

    # ── Checkpoint (Stop hook) ───────────────────────────────────

    def checkpoint(self) -> None:
        """Process raw events into session-level summaries. Stop hook calls this."""
        events = self.read_events()
        if not events:
            return

        # Group events by phase
        phase_events: dict[Phase, list[SkillEvent]] = {}
        for event in events:
            if event.phase:
                phase_events.setdefault(event.phase, []).append(event)

        # Write checkpoint metadata
        meta = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_count": len(events),
            "phases_seen": [p.value for p in phase_events.keys()],
        }
        self._atomic_write_json(self.config.raw_dir / "checkpoint.json", meta)

    # ── Archive (session end) ────────────────────────────────────

    def archive(self) -> None:
        """Compact raw events after session end. Keeps index + task records intact."""
        # Deduplicate events by same skill+args within a time window
        events = self.read_events()
        # Simple dedup: keep unique skill+args combinations
        seen: set[str] = set()
        unique: list[SkillEvent] = []
        for e in events:
            key = f"{e.skill_name}:{e.skill_args or ''}"
            if key not in seen:
                seen.add(key)
                unique.append(e)

        # Rewrite events with only unique entries
        path = self.config.raw_dir / "events.jsonl"
        content = "".join(e.model_dump_json() + "\n" for e in unique)
        path.write_text(content, encoding="utf-8")