#!/bin/bash
# MigBotMemory — Stop hook
# Processes raw skill events into session-level checkpoints

set -e

PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
MBM_DIR="$PROJECT_ROOT/.mbm"

if [ ! -d "$MBM_DIR" ]; then
  exit 0
fi

mbm checkpoint 2>/dev/null || true
mbm briefing --write 2>/dev/null || true

echo '{"continue":true,"suppressOutput":true}'