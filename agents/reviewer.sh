#!/usr/bin/env bash

export ANTHROPIC_MODEL=opus
export ANTHROPIC_DEFAULT_OPUS_MODEL="glm-5.3[1m]"
export ANTHROPIC_BASE_URL="https://api.z.ai/api/anthropic"

exec /home/goga/bin/claude-as-claude.sh "$@"
