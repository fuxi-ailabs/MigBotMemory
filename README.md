# MigBotMemory

Universal compilation error pattern cache with progressive disclosure for code migration tools.

## Quick Start

```bash
# Install
pip install migbot-memory

# Initialize in your project
mbm init --domain android-to-harmonyos

# Generate briefing (inject into session context)
mbm briefing --write

# Write a new error pattern
mbm write \
  --signature "arkts-identifiers-as-prop-names.*ValuesBucket" \
  --domain android-to-harmonyos \
  --category syntax_error \
  --title "ValuesBucket computed property names forbidden" \
  --fix-strategy bracket_assignment \
  --fix-before "let bucket = { [keyName]: value }" \
  --fix-after "let bucket = {}; bucket[keyName] = value"

# Lookup pattern details (LLM on-demand retrieval)
mbm lookup "arkts-identifiers-as-prop-names"

# Promote pattern after consistent fixes
mbm promote android-to-harmonyos-arkts-identifiers-as-prop-names

# List all patterns
mbm list
```

## Integration with Claude Code

Copy the hooks configuration into your project's `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [{"type": "command", "command": ".mbm/hooks/on_session_start.sh", "timeout": 10}],
    "Stop": [{"type": "command", "command": ".mbm/hooks/on_stop.sh", "timeout": 5}],
    "SessionEnd": [{"type": "command", "command": ".mbm/hooks/on_session_end.sh", "timeout": 15}]
  }
}
```

Copy the hook scripts from `hooks/` into your project's `.mbm/hooks/` directory.

## Progressive Disclosure

Error patterns are stored in 3 tiers based on confidence:

| Tier | Confidence | Injection Strategy | Token Budget |
|---|---|---|---|
| Deterministic | 1.0 | Always inject full fix | ≤500 |
| Probabilistic | 0.7~0.99 | Inject on signature match | ≤1000 |
| Empirical | 0.5~0.69 | On-demand via lookup | ≤2000 |

Total budget ≤4000 tokens. Patterns promote automatically after consistent fixes.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design document.