# Source me: shared environment for the simulator scripts.
DSM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DSM_ROOT
export DSM_SIM_HOME="${DSM_SIM_HOME:-/opt/sim}"
export GZ_VERSION=harmonic
export GZ_SIM_SYSTEM_PLUGIN_PATH="$DSM_SIM_HOME/ardupilot_gazebo/build${GZ_SIM_SYSTEM_PLUGIN_PATH:+:$GZ_SIM_SYSTEM_PLUGIN_PATH}"
export GZ_SIM_RESOURCE_PATH="$DSM_ROOT/sim/models:$DSM_ROOT/sim/generated/models:$DSM_SIM_HOME/ardupilot_gazebo/models${GZ_SIM_RESOURCE_PATH:+:$GZ_SIM_RESOURCE_PATH}"
# Headless rendering on CPU (no GPU in CI/cloud): EGL + Mesa llvmpipe.
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
# llvmpipe spawns one render thread per core by default; leave cores for the vision models
export LP_NUM_THREADS="${LP_NUM_THREADS:-2}"
export DSM_RUN_DIR="${DSM_RUN_DIR:-/tmp/drone_search_run}"
export DSM_FRAME_DIR="${DSM_FRAME_DIR:-/dev/shm/drone_search}"
# Ground truth lives outside the repo and outside anything the server may read.
export DSM_EVAL_DIR="${DSM_EVAL_DIR:-$HOME/.drone_search_eval}"
export DSM_SYS_PYTHON="${DSM_SYS_PYTHON:-/usr/bin/python3.12}"
