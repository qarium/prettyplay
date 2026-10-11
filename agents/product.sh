#!/usr/bin/env bash

export CODEX_MODEL="gpt-6-astra"
export CODEX_REASONING="high"

exec /home/goga/bin/codex-as-claude.sh "$@"
