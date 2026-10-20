#!/usr/bin/env bash
# Demo: generate a random scenario, start the simulator, let Claude find the target through
# the MCP tools, score it against the hidden ground truth and render a flight video.
#
#   scripts/demo.sh [easy|medium|hard] [seed]
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
TIER="${1:-easy}"
SEED="${2:-$RANDOM}"
.venv/bin/python eval/run.py --n 1 --tiers "$TIER" --seed0 "$SEED" --version "demo-$TIER-$SEED" --video
echo "video:   eval/results/demo-$TIER-$SEED/$TIER-$(printf %04d "$SEED")/flight.mp4"
echo "results: eval/results/demo-$TIER-$SEED/results.md"
