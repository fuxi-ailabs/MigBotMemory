# MigBotMemory

Task lifecycle memory for code migration — record the complete feature migration cycle, compress it, and reuse it.

## Quick Start

```bash
pip install migbot-memory

# Initialize
mbm init --domain android-to-harmonyos

# Record a complete feature migration (task→plan→execute→verify→commit)
mbm record \
  --id login-page \
  --feature LoginActivity \
  --source LoginActivity.java \
  --target LoginPage.ets \
  --task-summary "迁移登录页面" \
  --plan-summary "用Column+TextInput" \
  --execute-summary "XML转Column" \
  --verify-summary "编译通过" \
  --outcome success \
  --compile-pass true --verify-pass true

# Search similar migrations
mbm search LoginActivity

# Generate briefing for session context injection
mbm briefing --write

# Lookup full lifecycle details (lossless)
mbm lookup login-page
```

## Integration with Claude Code

Add to project `.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {"type": "command", "command": ".mbm/hooks/on_skill_use.sh", "matcher": "Skill", "timeout": 3}
    ],
    "Stop": [
      {"type": "command", "command": ".mbm/hooks/on_stop.sh", "timeout": 5}
    ]
  }
}
```

Copy hook scripts from `hooks/` into `.mbm/hooks/`.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design document.

**Key concepts:**
- Memory unit = feature migration lifecycle (task→plan→execute→verify→commit)
- 3-level compression: tool → session (split+summarize+index) → task
- Task hooks = skill invocations (PostToolUse), not session boundaries
- Quality-based categorization: reference (success) vs trial (partial/failed)