#!/usr/bin/env bash
set -euo pipefail

# rattler-build strips the archive top-level dir, so the repo lands in src/.
cd src/isaac_ros_common

export AMENT_PREFIX_PATH="${PREFIX}${AMENT_PREFIX_PATH:+:${AMENT_PREFIX_PATH}}"
export CMAKE_PREFIX_PATH="${PREFIX}${CMAKE_PREFIX_PATH:+:${CMAKE_PREFIX_PATH}}"

export CUDACXX="${BUILD_PREFIX}/bin/nvcc"

# Ampere and newer, matching Isaac ROS 4.5's supported GPUs, plus PTX for later.
cmake -S . -B build -G Ninja ${CMAKE_ARGS:-} \
  -DCMAKE_CUDA_COMPILER="${CUDACXX}" \
  -DCMAKE_CUDA_ARCHITECTURES="${CUDA_ARCHITECTURES:-$(case "${target_platform:-$(uname -m)}" in linux-aarch64|aarch64) echo "87;110;120";; *) echo "80;86;89;90";; esac)}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="${PREFIX}" \
  -DCMAKE_PREFIX_PATH="${PREFIX}" \
  -DPYTHON_EXECUTABLE="${PREFIX}/bin/python" \
  -DBUILD_TESTING=OFF

cmake --build build --parallel "${CPU_COUNT:-2}"
cmake --install build
