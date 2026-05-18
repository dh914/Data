#!/bin/bash
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

if [ -f requirements.txt ]; then
  pip install --quiet --disable-pip-version-check -r requirements.txt
fi

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export AGENT_REPO=\"\${AGENT_REPO:-dh914/Agent}\""
    echo "export INSTRUCTION_LABEL=\"\${INSTRUCTION_LABEL:-data-request}\""
  } >> "$CLAUDE_ENV_FILE"
fi
