#!/usr/bin/env bash
# One command to bring up the simulator: Gazebo Harmonic (headless) + ArduCopter SITL +
# camera frame bridge.  Usage: scripts/sim_up.sh [--scenario path/to/scenario.json]
set -euo pipefail
source "$(dirname "$0")/env.sh"
[ -d "$DSM_ROOT/sim/generated/models/search_drone" ] || "$DSM_ROOT/.venv/bin/python" "$DSM_ROOT/sim/build_assets.py"
exec "$DSM_ROOT/.venv/bin/python" "$DSM_ROOT/sim/launch.py" up "$@"
