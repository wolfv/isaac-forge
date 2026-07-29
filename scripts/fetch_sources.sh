#!/usr/bin/env bash
# Populate .srccache/ with the upstream tarballs that scripts/gen_source.py inspects
# to detect per-package build traits. Same URLs and hashes the recipes use.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE="${ROOT}/.srccache"
mkdir -p "${CACHE}"

fetch() {  # repo url
  local repo="$1" url="$2"
  [ -d "${CACHE}/${repo}" ] && { echo "  = ${repo}"; return; }
  local tmp; tmp="$(mktemp)"
  curl -fsSL -o "${tmp}" "${url}"
  mkdir -p "${CACHE}/${repo}"
  tar xzf "${tmp}" -C "${CACHE}/${repo}" --strip-components=1
  rm -f "${tmp}"
  echo "  + ${repo}"
}

B=https://github.com/NVIDIA-ISAAC-ROS
fetch isaac_ros_nitros         "$B/isaac_ros_nitros/archive/refs/tags/v4.5-0.tar.gz"
fetch isaac_ros_common         "$B/isaac_ros_common/archive/refs/tags/v4.5-0.tar.gz"
fetch isaac_ros_image_pipeline "$B/isaac_ros_image_pipeline/archive/refs/tags/v4.5-0.tar.gz"
fetch isaac_ros_visual_slam    "$B/isaac_ros_visual_slam/archive/refs/tags/v4.5-0.tar.gz"
fetch isaac_ros_benchmark      "$B/isaac_ros_benchmark/archive/refs/tags/v4.5-0.tar.gz"
fetch ros2_benchmark           "$B/ros2_benchmark/archive/refs/tags/v4.5-0.tar.gz"
fetch isaac_ros_manipulation   "$B/isaac_ros_manipulation/archive/refs/tags/v4.5-0.tar.gz"
fetch isaac_ros_cumotion       "$B/isaac_ros_cumotion/archive/refs/tags/v4.5-0.tar.gz"
fetch isaac_ros_nvblox         "$B/isaac_ros_nvblox/archive/refs/tags/v4.5-0.tar.gz"
# For isaac_ros_segment_anything2_interfaces, which isaac_ros_manipulation_servers needs.
fetch isaac_ros_image_segmentation "$B/isaac_ros_image_segmentation/archive/refs/tags/v4.5-0.tar.gz"
fetch isaac_ros_pose_estimation "$B/isaac_ros_pose_estimation/archive/refs/tags/v4.5-0.tar.gz"
# Two of its four packages -- tensor_proc and dnn_image_encoder -- carry no TensorRT and
# no Triton, which is what puts isaac_ros_foundationpose in reach. See gen_source.py.
fetch isaac_ros_dnn_inference "$B/isaac_ros_dnn_inference/archive/refs/tags/v4.5-0.tar.gz"
fetch negotiated "https://github.com/osrf/negotiated/archive/eac198b55dcd052af5988f0f174902913c5f20e7.tar.gz"
# Not NVIDIA's: two open-source ROS packages the manipulation stack needs and RoboStack
# does not carry. topic_based_ros2_control has no jazzy release at all (ISSUES.md #15), so
# it is pinned to a commit; robotiq_controllers does, and is pinned to the release tag.
fetch topic_based_ros2_control \
  "https://github.com/PickNikRobotics/topic_based_ros2_control/archive/6bd8d55e1c4ad3188770fe5c8b93b942bcede4a2.tar.gz"
fetch robotiq_controllers \
  "https://github.com/ros2-gbp/ros2_robotiq_gripper-release/archive/refs/tags/release/jazzy/robotiq_controllers/0.0.1-3.tar.gz"
echo "  cache: $(du -sh "${CACHE}" | cut -f1)"
