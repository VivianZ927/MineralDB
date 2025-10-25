#!/usr/bin/env bash
set -xeuo pipefail
echo "CWD=$(pwd)"
echo "PORT=${PORT:-unset}"
ls -la

python - <<'PY'
import importlib, sys, traceback
print("sys.version:", sys.version)
try:
    m = importlib.import_module("Top20DB")  # change if needed
    print("Imported module OK. Has server:", hasattr(m, "server"))
except Exception:
    traceback.print_exc()
    raise
PY

exec gunicorn Top20DB:server --bind 0.0.0.0:$PORT --log-level debug --error-logfile - --access-logfile -
