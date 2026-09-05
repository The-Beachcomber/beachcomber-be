#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python -m venv .venv
# shellcheck disable=SC1091
source .venv/{bin,Scripts}/activate 2>/dev/null || source .venv/Scripts/activate
pip install -q -r requirements-dev.txt
exec uvicorn app.main:app --reload --host 0.0.0.0 --port "${PORT:-8000}"
