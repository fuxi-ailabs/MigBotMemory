# MigBotMemory Project

## Design Principles

- **Memory unit = feature migration lifecycle**, not individual error patterns
- **3-level compression**: tool (structured events) → session (split+summarize+index) → task (phase summaries + key artifacts)
- **Task hooks = skill invocations** (PostToolUse with Skill matcher), NOT session boundaries
- **Quality-based categorization**: reference (success) vs trial (partial/failed), NO confidence scores
- **Lossless**: full lifecycle preserved in JSON, disclosed progressively via phase summaries

## Project Structure

- `src/mbm/models.py` — TaskRecord, SkillEvent, Phase, Outcome, QualityMetrics
- `src/mbm/config.py` — MBMConfig with phase_map (skill→phase mapping)
- `src/mbm/store.py` — TaskStore (raw events, task CRUD, index, checkpoint, archive)
- `src/mbm/inject.py` — BriefingGenerator (progressive disclosure, budget trimming)
- `src/mbm/cli.py` — typer CLI: init, record, event, briefing, lookup, search, checkpoint, archive, list
- `hooks/` — PostToolUse(Skill) and Stop hook scripts
- `tests/` — 27 passing tests