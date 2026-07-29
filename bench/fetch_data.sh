#!/usr/bin/env bash
# Fetch NVIDIA's r2b_storage dataset from NGC (public, no credentials).
# 2.9 GB. Note it lives under r2bdataset2023, not the 2024 resource that hosts
# r2b_galileo -- the benchmark scripts do not say which.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${HERE}/assets/datasets/r2b_dataset/r2b_storage"
BASE='https://api.ngc.nvidia.com/v2/resources/org/nvidia/team/isaac/r2bdataset2023/1/files?redirect=true&path=r2b_storage'
mkdir -p "${DEST}"
[ -s "${DEST}/metadata.yaml" ] || curl -fsSL -o "${DEST}/metadata.yaml" "${BASE}/metadata.yaml"
[ -s "${DEST}/r2b_storage_0.db3" ] || curl -fL --progress-bar -o "${DEST}/r2b_storage_0.db3" "${BASE}/r2b_storage_0.db3"
# The harness resolves assets via ${ISAAC_ROS_WS}/src/ros2_benchmark/assets and
# ignores assets_root:= on the command line, so satisfy that layout with a symlink.
mkdir -p "${HERE}/ws/src/ros2_benchmark"
ln -sfn "${HERE}/assets" "${HERE}/ws/src/ros2_benchmark/assets"
echo "==> ready: $(du -sh "${DEST}" | cut -f1)"
