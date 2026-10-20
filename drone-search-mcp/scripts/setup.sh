#!/usr/bin/env bash
# One-command setup on Ubuntu 24.04 (x86_64): Gazebo Harmonic, ArduCopter SITL,
# ardupilot_gazebo plugin, Python venv, simulation assets and vision model weights.
#
#   scripts/setup.sh            # everything (needs sudo for apt)
#   SKIP_APT=1 scripts/setup.sh # if Gazebo and the build deps are already installed
#
# Installs simulator pieces under $DSM_SIM_HOME (default /opt/sim).
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

if [ -z "${SKIP_APT:-}" ]; then
  echo "[setup] apt: Gazebo Harmonic + build deps"
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq curl lsb-release gnupg git cmake build-essential ffmpeg >/dev/null
  $SUDO curl -sS https://packages.osrfoundation.org/gazebo.gpg -o /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] http://packages.osrfoundation.org/gazebo/ubuntu-stable $(lsb_release -cs) main" \
    | $SUDO tee /etc/apt/sources.list.d/gazebo-stable.list >/dev/null
  $SUDO apt-get update -qq
  DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq gz-harmonic libgz-sim8-dev rapidjson-dev \
    libopencv-dev libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev gstreamer1.0-plugins-bad \
    gstreamer1.0-libav gstreamer1.0-gl python3-gz-transport13 python3-gz-msgs10 python3-numpy python3-pil \
    libegl1 libgl1-mesa-dri >/dev/null
fi

$SUDO mkdir -p "$DSM_SIM_HOME" && $SUDO chown "$(id -u)":"$(id -g)" "$DSM_SIM_HOME"
if [ ! -x "$DSM_SIM_HOME/arducopter" ]; then
  echo "[setup] ArduCopter SITL (prebuilt, stable)"
  curl -sS -o "$DSM_SIM_HOME/arducopter" https://firmware.ardupilot.org/Copter/stable/SITL_x86_64_linux_gnu/arducopter
  chmod +x "$DSM_SIM_HOME/arducopter"
fi
if [ ! -d "$DSM_SIM_HOME/ardupilot/Tools/autotest/default_params" ]; then
  echo "[setup] ArduPilot default parameter files"
  git clone -q --depth 1 --filter=blob:none --sparse https://github.com/ArduPilot/ardupilot "$DSM_SIM_HOME/ardupilot"
  git -C "$DSM_SIM_HOME/ardupilot" sparse-checkout set Tools/autotest/default_params
fi
if [ ! -f "$DSM_SIM_HOME/ardupilot_gazebo/build/libArduPilotPlugin.so" ]; then
  echo "[setup] ardupilot_gazebo plugin"
  [ -d "$DSM_SIM_HOME/ardupilot_gazebo" ] || git clone -q --depth 1 https://github.com/ArduPilot/ardupilot_gazebo "$DSM_SIM_HOME/ardupilot_gazebo"
  cmake -S "$DSM_SIM_HOME/ardupilot_gazebo" -B "$DSM_SIM_HOME/ardupilot_gazebo/build" -DCMAKE_BUILD_TYPE=RelWithDebInfo >/dev/null
  cmake --build "$DSM_SIM_HOME/ardupilot_gazebo/build" -j"$(nproc)" >/dev/null
fi

if [ ! -x .venv/bin/python ]; then
  echo "[setup] Python venv (CPU torch)"
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
  uv venv -q --python 3.12 .venv
  uv pip install -q --python .venv/bin/python --index-url https://download.pytorch.org/whl/cpu torch
  uv pip install -q --python .venv/bin/python -e ".[eval,dev]"
fi

echo "[setup] simulation assets (textures, drone model, Fuel models)"
.venv/bin/python sim/build_assets.py --ardupilot-gazebo "$DSM_SIM_HOME/ardupilot_gazebo"

echo "[setup] vision model weights"
.venv/bin/python - <<'EOF'
from vision import models
models.clip(); models.owl(); models.dino()
EOF
echo "[setup] done. Try: scripts/demo.sh"
