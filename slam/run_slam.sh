#!/usr/bin/env bash
# cuVSLAM on NVIDIA's r2b Galileo dataset, end to end.
#
#   bag (H.264, 4 stereo pairs, 22 s)
#     -> h264_bridge.py   CPU decode of the front pair to mono8
#     -> VisualSlamNode   cuVSLAM stereo tracking on the GPU
#     -> measure_trajectory.py  integrates the path and compares to wheel odom
#
# No pipefail: `producer | grep -q` exits non-zero when it matches, because grep -q
# closes the pipe and the producer dies of SIGPIPE.
set -u

BAG="${1:-data/r2b_galileo}"
[ -d "${BAG}" ] || { echo "!! bag not found: ${BAG} (run ./fetch_data.sh)"; exit 1; }

LOG_SLAM="$(mktemp)"; LOG_BRIDGE="$(mktemp)"
PIDS=()
cleanup() {
  for p in "${PIDS[@]:-}"; do [ -n "${p}" ] && kill "${p}" 2>/dev/null; done
  wait 2>/dev/null
}
trap cleanup EXIT

echo "==> starting cuVSLAM"
ros2 launch launch/r2b_galileo_vslam.launch.py > "${LOG_SLAM}" 2>&1 &
PIDS+=($!)

for _ in $(seq 40); do
  sleep 1
  nodes="$(ros2 node list 2>/dev/null)"
  case "${nodes}" in *visual_slam*) break ;; esac
done
case "$(ros2 node list 2>/dev/null)" in
  *visual_slam*) echo "    visual_slam up" ;;
  *) echo "!! visual_slam did not come up"; cat "${LOG_SLAM}"; exit 1 ;;
esac
grep -E 'cuVSLAM version|WarmUpGPU' "${LOG_SLAM}" | sed 's/.*\]: /    /'

if [ "${USE_NVDEC:-1}" = "0" ]; then
  echo "==> starting the CPU H.264 bridge (USE_NVDEC=0)"
  python h264_bridge.py > "${LOG_BRIDGE}" 2>&1 &
  PIDS+=($!)
  sleep 3
else
  echo "==> NVDEC decoding in-container (set USE_NVDEC=0 for the CPU fallback)"
fi

echo "==> playing the bag (22 s of Nova multi-camera data)"
ros2 bag play "${BAG}" --storage mcap --clock > /dev/null 2>&1 &
PIDS+=($!)

python measure_trajectory.py 32
rc=$?

echo
echo "==> decode throughput"
grep 'decoded frames' "${LOG_BRIDGE}" | tail -2 | sed 's/.*\]: /    /'
echo "==> cuVSLAM log"
grep -iE 'cuvslam|track|error|warn' "${LOG_SLAM}" | grep -viE 'WarmUpGPU|version' | tail -6 | sed 's/^/    /'

exit "${rc}"
