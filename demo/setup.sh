#!/usr/bin/env bash
# Stand up a runnable Isaac ROS demo on top of RoboStack.
#
# This is the fast prototype of the repack path: rather than building 23 conda
# packages, it overlays the official Isaac ROS debs straight onto the pixi env
# and lets the loader sort it out. If this runs, per-package repack recipes will
# work too -- the ABI question is the same either way.
#
#   ./setup.sh            # fetch + overlay, then print how to run
#   ./setup.sh --clean    # remove the overlaid files and start over
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "${HERE}")"
ENV_DIR="${HERE}/.pixi/envs/default"
CACHE="${HERE}/.cache"
TARGETS="ros-jazzy-isaac-ros-image-proc
ros-jazzy-isaac-ros-stereo-image-proc
ros-jazzy-isaac-ros-depth-image-proc
ros-jazzy-isaac-ros-visual-slam
ros-jazzy-isaac-ros-apriltag"

APT_BASE="https://isaac.download.nvidia.com/isaac-ros/release-4"
PACKAGES_URL="${APT_BASE}/dists/noble/main/binary-amd64/Packages"

if [ "${1:-}" = "--clean" ]; then
  rm -rf "${CACHE}"
  echo "cache cleared; run 'pixi clean' then 'pixi install' to reset the env too"
  exit 0
fi

mkdir -p "${CACHE}/debs"

echo "==> installing the RoboStack environment"
( cd "${HERE}" && pixi install )

echo "==> fetching the Isaac ROS apt index"
[ -f "${CACHE}/Packages" ] || curl -fsSL -o "${CACHE}/Packages" "${PACKAGES_URL}"

echo "==> resolving the combined dependency closure"
python3 "${ROOT}/scripts/aptclosure.py" --urls "${CACHE}/Packages" ${TARGETS} \
  > "${CACHE}/urls.txt"
echo "    $(wc -l < "${CACHE}/urls.txt") debs in the closure"

echo "==> downloading debs (cached in ${CACHE}/debs)"
( cd "${CACHE}/debs" && xargs -a "${CACHE}/urls.txt" -P 6 -n 1 curl -fsSL -O --remote-time -z )

echo "==> building the VPI package if it is not already built"
VPI_PKG="$(ls "${ROOT}"/output/linux-64/vpi-*.conda 2>/dev/null | head -1 || true)"
if [ -z "${VPI_PKG}" ]; then
  ( cd "${ROOT}" && pixi run vpi )
  VPI_PKG="$(ls "${ROOT}"/output/linux-64/vpi-*.conda | head -1)"
fi

echo "==> overlaying VPI"
TMP="$(mktemp -d)"
( cd "${TMP}" && bsdtar -xf "${VPI_PKG}" && bsdtar -xf pkg-vpi-*.tar.zst )
cp -a "${TMP}/lib/."     "${ENV_DIR}/lib/"
cp -a "${TMP}/include/." "${ENV_DIR}/include/"
rm -rf "${TMP}"

echo "==> overlaying the closure"
"${ROOT}/scripts/overlay_debs.sh" "${ENV_DIR}" "${CACHE}"/debs/*.deb

echo "==> installing the GXF loader-path activation hook"
mkdir -p "${ENV_DIR}/etc/conda/activate.d"
cp "${HERE}/activate.d/zz-isaac-gxf.sh" "${ENV_DIR}/etc/conda/activate.d/"

cat <<'EOF'

==> ready.

Run the demo:

    cd demo
    pixi run demo

That starts an rclcpp component container and loads
nvidia::isaac_ros::image_proc::ResizeNode into it.

Requires NVIDIA driver >= 580 (Isaac ROS 4.5 is built against CUDA 13.0).
Check yours with:  nvidia-smi --query-gpu=driver_version --format=csv
EOF
