#!/usr/bin/env bash
# Clone the Isaac ROS sources into src/.
#
# By default this does a metadata-only checkout (package.xml, CMakeLists.txt,
# *.cmake, *.md, *.yaml) which is all scripts/inventory.py needs and keeps the
# tree small. Pass --full for complete checkouts, which is what you need to
# actually build; add --lfs to also fetch the vendored GXF and cuVSLAM binaries.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${ROOT}/src"
MODE="meta"
LFS="no"

for arg in "$@"; do
  case "${arg}" in
    --full) MODE="full" ;;
    --lfs)  MODE="full"; LFS="yes" ;;
    *) echo "usage: $0 [--full] [--lfs]" >&2; exit 2 ;;
  esac
done

REPOS=(
  isaac_ros_common isaac_ros_nitros gxf
  isaac_ros_image_pipeline isaac_ros_visual_slam isaac_ros_apriltag
  isaac_ros_dnn_inference isaac_ros_nvblox isaac_ros_object_detection
  isaac_ros_image_segmentation isaac_ros_pose_estimation isaac_ros_cumotion
  isaac_ros_dnn_stereo_depth isaac_ros_compression isaac_ros_depth_segmentation
  isaac_ros_examples isaac_ros_benchmark ros2_benchmark
  isaac_ros_mapping_and_localization isaac_ros_data_tools isaac_ros_nova
  isaac_ros_argus_camera isaac_ros_deploy isaac_ros_manipulation
  isaac_ros_freespace_segmentation isaac_ros_map_localization
  isaac_ros_physical_ai isaac_ros_learned_policies isaac_ros_teleop
  isaac_ros_robots isaac_ros_jetson isaac_ros_cloud_control
  isaac_ros_sipl_camera isaac_ros_nitros_bridge isaac_ros_noetic_interfaces
)

mkdir -p "${SRC}"

clone_one() {
  local repo="$1" dir="${SRC}/$1"
  [ -d "${dir}/.git" ] && { echo "  = ${repo} (exists)"; return; }

  if [ "${MODE}" = "full" ]; then
    if [ "${LFS}" = "yes" ]; then
      git clone -q --depth 1 "https://github.com/NVIDIA-ISAAC-ROS/${repo}.git" "${dir}"
    else
      GIT_LFS_SKIP_SMUDGE=1 git clone -q --depth 1 \
        "https://github.com/NVIDIA-ISAAC-ROS/${repo}.git" "${dir}"
    fi
  else
    git clone -q --depth 1 --filter=blob:none --no-checkout \
      "https://github.com/NVIDIA-ISAAC-ROS/${repo}.git" "${dir}"
    git -C "${dir}" sparse-checkout set --no-cone \
      '*.xml' '*.txt' '*.cmake' '*.md' '*.yaml' 'LICENSE' >/dev/null
    git -C "${dir}" checkout -q
  fi
  echo "  + ${repo}"
}

echo "cloning ${#REPOS[@]} repos into src/ (mode=${MODE}, lfs=${LFS})"
for repo in "${REPOS[@]}"; do
  clone_one "${repo}" &
done
wait

echo "done: $(find "${SRC}" -name package.xml | wc -l) package.xml files"
