#!/bin/bash
# MigBotMemory — SessionEnd hook
# Archive and compact pattern store at session end

set -e

PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
MBM_DIR="$PROJECT_ROOT/.mbm"

if [ ! -d "$MBM_DIR" ]; then
  exit 0
fi

mbm archive 2>/dev/null || true

echo '{"continue":true,"suppressOutput":true}'