#!/usr/bin/env bash
set -euo pipefail

# rattler-build strips the archive top-level dir, so the repo lands in src/.
# Build only the decoder; isaac_ros_h264_encoder is a separate package.
cd src/isaac_ros_h264_decoder

# ament_auto_find_build_dependencies() and find_package(vpi) both read from the
# host prefix.
export AMENT_PREFIX_PATH="${PREFIX}${AMENT_PREFIX_PATH:+:${AMENT_PREFIX_PATH}}"
export CMAKE_PREFIX_PATH="${PREFIX}${CMAKE_PREFIX_PATH:+:${CMAKE_PREFIX_PATH}}"

# The nvv4l2 libraries live in $PREFIX/lib here, not /usr/lib/x86_64-linux-gnu.
# The patched CMakeLists takes the directory from NVBUF_LIB_DIR, so point it at the
# prefix rather than carrying a second patch for the paths.
# ${CMAKE_ARGS} carries the compiler activation's CMAKE_FIND_ROOT_PATH, which is what
# points find_package(CUDAToolkit) at the prefix instead of /usr/local/cuda. The CUDA
# activation script sets it specifically for "projects that don't enable the CUDA
# language but use FindCUDAToolkit" -- exactly this package. Dropping it silently
# reintroduces the host-CUDA leak.
cmake -S . -B build -G Ninja ${CMAKE_ARGS:-} \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="${PREFIX}" \
  -DCMAKE_PREFIX_PATH="${PREFIX}" \
  -DNVBUF_LIB_DIR="${PREFIX}/lib" \
  -DPYTHON_EXECUTABLE="${PREFIX}/bin/python" \
  -DBUILD_TESTING=OFF

cmake --build build --parallel "${CPU_COUNT:-2}"
cmake --install build
