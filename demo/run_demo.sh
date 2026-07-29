#!/usr/bin/env bash
# Start an rclcpp component container and load an Isaac ROS node into it.
#
# On a machine with NVIDIA driver >= 580 the node loads and stays resident. On an
# older driver it loads the library and finds the class, then throws
# cudaErrorInsufficientDriver from the constructor -- which still proves the
# packaging, linking and pluginlib layers are all correct.
# No pipefail: `producer | grep -q pattern` exits non-zero *when it matches*,
# because grep -q closes the pipe and the producer dies of SIGPIPE. Whether that
# happens is a race on output size, which made node detection flaky here.
set -u

COMPONENT="${1:-nvidia::isaac_ros::image_proc::ResizeNode}"
PACKAGE="${2:-isaac_ros_image_proc}"
LOG="$(mktemp)"

cleanup() { [ -n "${PID:-}" ] && kill "${PID}" 2>/dev/null; wait "${PID:-}" 2>/dev/null; }
trap cleanup EXIT

echo "==> starting node container (rclcpp_components, not Docker)"
ros2 run rclcpp_components component_container --ros-args -r __node:=isaac_container \
  > "${LOG}" 2>&1 &
PID=$!

# Capture, then match in-shell -- no pipeline to misread.
up=""
for _ in $(seq 30); do
  sleep 1
  nodes="$(ros2 node list 2>/dev/null)"
  case "${nodes}" in *isaac_container*) up=1; break ;; esac
done

if [ -z "${up}" ]; then
  echo "!! node container did not come up"; cat "${LOG}"; exit 1
fi
echo "    node container up: /isaac_container"

echo "==> loading ${COMPONENT}"
ros2 component load /isaac_container "${PACKAGE}" "${COMPONENT}" 2>&1 | sed 's/^/    /'

echo
echo "==> container log"
sed 's/^/    /' "${LOG}"

if grep -q 'cudaErrorInsufficientDriver' "${LOG}"; then
  cat <<'EOF'

==> Diagnosis: packaging works, driver is too old.

The library loaded, pluginlib found and instantiated the class, and the only
failure was creating a CUDA stream. Isaac ROS 4.5 is built against CUDA 13.0,
which needs NVIDIA driver >= 580.

    nvidia-smi --query-gpu=driver_version --format=csv
EOF
fi
