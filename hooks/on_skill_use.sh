#!/bin/bash
# MigBotMemory — PostToolUse(Skill) hook
# Captures skill invocations and records them as lifecycle events
# This is the TASK-LEVEL hook, not session-level

set -e

PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
MBM_DIR="$PROJECT_ROOT/.mbm"

if [ ! -d "$MBM_DIR" ]; then
  # No .mbm directory — graceful degradation, skip silently
  exit 0
fi

# Read JSON from stdin (Claude Code sends tool call data)
INPUT=$(cat)

# Extract skill name and args from the JSON
SKILL_NAME=$(echo "$INPUT" | python -c "
import json, sys
try:
    data = json.load(sys.stdin)
    tool_input = data.get('tool_input', {})
    name = tool_input.get('skill', '')
    args = tool_input.get('args', '')
    print(name)
except: print('')
" 2>/dev/null || echo "")

SKILL_ARGS=$(echo "$INPUT" | python -c "
import json, sys
try:
    data = json.load(sys.stdin)
    tool_input = data.get('tool_input', {})
    args = tool_input.get('args', '')
    print(args)
except: print('')
" 2>/dev/null || echo "")

if [ -z "$SKILL_NAME" ]; then
  exit 0
fi

# Record the skill invocation event
mbm event --skill-name "$SKILL_NAME" --skill-args "$SKILL_ARGS" 2>/dev/null || true

echo '{"continue":true,"suppressOutput":true}'