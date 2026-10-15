#!/bin/zsh
# launchd가 월요일 12:00(점검)·15:00(실행)에 호출하는 래퍼
cd "$(dirname "$0")" || exit 1
PY="${PYTHON:-$(command -v python3)}"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
mkdir -p logs
LOG="logs/notebook_$(date +%Y-%m-%d).log"
"$PY" notebook_sync.py "$@" >> "$LOG" 2>&1
