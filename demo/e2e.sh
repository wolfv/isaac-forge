#!/usr/bin/env bash
# End-to-end GPU test: start a node container, load ResizeNode at 320x240, push a
# 640x480 image through it, and verify the GPU-resized result comes back.
#
# No pipefail -- see the note in run_demo.sh about `grep -q` and SIGPIPE.
set -u

LOG="$(mktemp)"
cleanup() { [ -n "${PID:-}" ] && kill "${PID}" 2>/dev/null; wait "${PID:-}" 2>/dev/null; }
trap cleanup EXIT

echo "==> starting node container (rclcpp_components, not Docker)"
ros2 run rclcpp_components component_container --ros-args -r __node:=isaac_container \
  > "${LOG}" 2>&1 &
PID=$!

up=""
for _ in $(seq 30); do
  sleep 1
  nodes="$(ros2 node list 2>/dev/null)"
  case "${nodes}" in *isaac_container*) up=1; break ;; esac
done
[ -n "${up}" ] || { echo "!! node container did not come up"; cat "${LOG}"; exit 1; }

echo "==> loading ResizeNode at 320x240"
ros2 component load /isaac_container isaac_ros_image_proc \
  nvidia::isaac_ros::image_proc::ResizeNode \
  -p output_width:=320 -p output_height:=240 2>&1 | sed 's/^/    /'
sleep 2

echo "==> pushing an image through the GPU"
python e2e_resize.py
rc=$?

echo
echo "==> node container log"
sed 's/^/    /' "${LOG}"
exit "${rc}"
