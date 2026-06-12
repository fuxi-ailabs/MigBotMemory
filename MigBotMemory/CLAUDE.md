# MigBotMemory Project

This is the MigBotMemory repository — a universal compilation error pattern cache with progressive disclosure for code migration tools.

## Key Design Decisions

- **3-tier progressive disclosure** (not 4): deterministic / probabilistic / empirical
- **JSON file storage** (not SQLite): error patterns are small, regex-based data
- **hooks-driven session lifecycle** (not skills): guaranteed by Claude Code harness
- **Lossless compression**: pattern preserves title + facts + fix_template, disclosed progressively
- **Domain tags**: each migration tool has its own domain, patterns are isolated

## Project Structure

- `src/mbm/` — Core Python package (models, store, inject, cli, config)
- `hooks/` — Claude Code hook scripts and configuration
- `examples/` — Sample patterns for Android→HarmonyOS
- `tests/` — Unit and integration tests
- `ARCHITECTURE.md` — Full architecture document

## Running Tests

```bash
cd C:\AI\MigBotMemory
pip install -e ".[dev]"
pytest tests/
```