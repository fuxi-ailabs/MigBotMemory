#!/bin/bash
# MigBotMemory — Stop hook
# Checkpoint session state after every Claude response
# Lightweight (<50ms) — persists pending patterns

set -e

PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
MBM_DIR="$PROJECT_ROOT/.mbm"

if [ ! -d "$MBM_DIR" ]; then
  exit 0
fi

mbm checkpoint 2>/dev/null || true

echo '{"continue":true,"suppressOutput":true}'