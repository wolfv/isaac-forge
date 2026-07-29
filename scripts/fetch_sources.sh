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
fetch negotiated "https://github.com/osrf/negotiated/archive/eac198b55dcd052af5988f0f174902913c5f20e7.tar.gz"
echo "  cache: $(du -sh "${CACHE}" | cut -f1)"
