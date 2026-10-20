#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/env.sh"
exec "$DSM_ROOT/.venv/bin/python" "$DSM_ROOT/sim/launch.py" down
