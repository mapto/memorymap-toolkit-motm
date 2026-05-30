#!/usr/bin/env bash
# validate.sh — lint, format-check, type-check, and test the notebook code
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

# Activate venv
PYTHON="notebook/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    echo "ERROR: venv not found at .venv/  — run 'uv sync' first"
    exit 1
fi

# PY_FILES=(api_client.py events.py locations.py main.py timespan.py)

FAIL=0

echo "=== ruff check ==="
if "$PYTHON" -m ruff check .; then
    echo "✓ ruff check passed"
else
    echo "✗ ruff check failed"
    FAIL=1
fi

echo ""
echo "=== ruff format (check only) ==="
if "$PYTHON" -m ruff format --check .; then
    echo "✓ ruff format passed"
else
    echo "✗ ruff format failed (run: uv run ruff format ${PY_FILES[*]})"
    FAIL=1
fi

echo ""
echo "=== pyright ==="
if "$PYTHON" -m pyright .; then
    echo "✓ pyright passed"
else
    echo "✗ pyright failed"
    FAIL=1
fi

echo ""
echo "=== pytest (including doctests) ==="
if "$PYTHON" -m pytest --doctest-modules . -v; then
    echo "✓ pytest passed"
else
    echo "✗ pytest failed"
    FAIL=1
fi

echo ""
if [ "$FAIL" -eq 0 ]; then
    echo "All checks passed ✓"
else
    echo "Some checks failed ✗"
    exit 1
fi
