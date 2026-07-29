#!/usr/bin/env bash
set -euo pipefail

# rattler-build strips the archive top-level dir, so the repo lands in src/.
# Build only the decoder; isaac_ros_h264_encoder is a separate package.
cd src/isaac_ros_h264_decoder

# conda-forge's magic_enum installs its headers into include/magic_enum/, and its CMake
# package exports only a target -- no magic_enum_INCLUDE_DIRS variable. So the include
# directory reaches consumers only if they link magic_enum::magic_enum through
# isaac_ros_gxf's imported target, which this package does not do: it picks up the gxf
# headers via ament include dirs instead. The result is
# `expected_macro.hpp:24: fatal error: magic_enum.hpp: No such file or directory`.
# State the directory rather than depending on that chain holding.
export CXXFLAGS="${CXXFLAGS:-} -I${PREFIX}/include/magic_enum"

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
