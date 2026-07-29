#!/usr/bin/env bash
# Fetch NVIDIA's r2b Galileo dataset from NGC. Public, no credentials needed.
#
# 22 s of Nova multi-camera data: four stereo pairs (H.264), two IMUs, wheel
# odometry, encoder ticks and the full calibration on /tf_static. 493 MB.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${HERE}/data/r2b_galileo"
BASE='https://api.ngc.nvidia.com/v2/resources/org/nvidia/team/isaac/r2bdataset2024/1/files?redirect=true&path=r2b_galileo'

mkdir -p "${DEST}"

if [ ! -s "${DEST}/metadata.yaml" ]; then
  echo "==> metadata.yaml"
  curl -fsSL -o "${DEST}/metadata.yaml" "${BASE}/metadata.yaml"
fi

if [ ! -s "${DEST}/r2b_galileo_0.mcap" ]; then
  echo "==> r2b_galileo_0.mcap (493 MB)"
  curl -fL --progress-bar -o "${DEST}/r2b_galileo_0.mcap" "${BASE}/r2b_galileo_0.mcap"
fi

echo "==> ready: $(du -sh "${DEST}" | cut -f1) in ${DEST#"${HERE}/"}"
