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
# All eight of its packages build: TensorRT is <exec_depend> in the three that use it and
# <test_depend> in detectnet, so none of them needs it to configure.
fetch isaac_ros_object_detection "$B/isaac_ros_object_detection/archive/refs/tags/v4.5-0.tar.gz"
# Two of its four packages build; the other two reference isaac_ros_visual_mapping, which
# does not exist at 4.5 (ISSUES.md #22).
fetch isaac_ros_mapping_and_localization "$B/isaac_ros_mapping_and_localization/archive/refs/tags/v4.5-0.tar.gz"
# Eight more repos, added in one pass. All are tagged v4.5-0 and all are small -- the
# largest tarball is isaac_ros_data_tools at 4.7 MB. isaac_ros_freespace_segmentation is
# deliberately absent: it has no v4.5-0 tag, only v3.2-13 (ISSUES.md #23).
fetch isaac_ros_apriltag           "$B/isaac_ros_apriltag/archive/refs/tags/v4.5-0.tar.gz"
fetch isaac_ros_compression        "$B/isaac_ros_compression/archive/refs/tags/v4.5-0.tar.gz"
fetch isaac_ros_teleop             "$B/isaac_ros_teleop/archive/refs/tags/v4.5-0.tar.gz"
# ESS and FoundationStereo. TensorRT is packaged now, and as in pose/ and detect/ the
# inference backend is a sibling composable node rather than a header these include.
fetch isaac_ros_dnn_stereo_depth   "$B/isaac_ros_dnn_stereo_depth/archive/refs/tags/v4.5-0.tar.gz"
# The VDA5050 fleet-interface layer -- thirteen packages, none proprietary.
fetch isaac_ros_cloud_control      "$B/isaac_ros_cloud_control/archive/refs/tags/v4.5-0.tar.gz"
fetch isaac_ros_data_tools         "$B/isaac_ros_data_tools/archive/refs/tags/v4.5-0.tar.gz"
fetch isaac_ros_jetson             "$B/isaac_ros_jetson/archive/refs/tags/v4.5-0.tar.gz"
fetch isaac_ros_examples           "$B/isaac_ros_examples/archive/refs/tags/v4.5-0.tar.gz"
fetch negotiated "https://github.com/osrf/negotiated/archive/eac198b55dcd052af5988f0f174902913c5f20e7.tar.gz"
# Not NVIDIA's, and not in RoboStack: topic_based_ros2_control has no jazzy release at all
# (ISSUES.md #15), so it is pinned to a commit. robotiq_controllers used to be here too and
# is now in robostack-jazzy, so it is gone.
fetch topic_based_ros2_control \
  "https://github.com/PickNikRobotics/topic_based_ros2_control/archive/6bd8d55e1c4ad3188770fe5c8b93b942bcede4a2.tar.gz"
echo "  cache: $(du -sh "${CACHE}" | cut -f1)"
