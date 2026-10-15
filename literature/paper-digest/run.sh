#!/bin/zsh
# launchd가 매주 월요일 호출하는 실행 래퍼
cd "$(dirname "$0")" || exit 1
PY="${PYTHON:-$(command -v python3)}"
mkdir -p logs
LOG="logs/run_$(date +%Y-%m-%d).log"
"$PY" weekly_papers.py >> "$LOG" 2>&1
