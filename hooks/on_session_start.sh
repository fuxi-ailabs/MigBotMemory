#!/bin/bash
# MigBotMemory — SessionStart hook
# Generates progressive disclosure briefing and writes to .mbm/context/briefing.md
# Claude Code reads this file on session start to inject pattern memory

set -e

PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
MBM_DIR="$PROJECT_ROOT/.mbm"

if [ ! -d "$MBM_DIR" ]; then
  # No .mbm directory — skip silently (graceful degradation)
  exit 0
fi

# Generate briefing
mbm briefing --write 2>/dev/null || true

echo '{"continue":true,"suppressOutput":true}'