#!/bin/bash
set -euo pipefail

# Only run in remote Claude Code on the web sessions
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Ensure the stories output directory exists for LO's writing workspace
mkdir -p "${CLAUDE_PROJECT_DIR}/stories"

# Persist any useful env vars for the session
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PROJECT_ROOT=\"${CLAUDE_PROJECT_DIR}\"" >> "$CLAUDE_ENV_FILE"
fi

echo "ENI's writing workspace is ready. Let's make something dark and beautiful."
