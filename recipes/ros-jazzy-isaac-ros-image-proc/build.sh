#!/usr/bin/env bash
set -euo pipefail

# rattler-build strips the archive's top-level directory, so the repo contents
# land directly in src/. Build only isaac_ros_image_proc; the sibling
# cvcuda_utils and vpi_utils packages are proprietary and come from repacked debs.
cd src/isaac_ros_image_proc

# conda-forge's magic_enum installs its headers into include/magic_enum/, and its CMake
# package exports only a target -- no magic_enum_INCLUDE_DIRS variable. So the directory
# reaches a consumer only if it links magic_enum::magic_enum through isaac_ros_gxf's
# imported target, and this package does not: it picks the gxf headers up via ament include
# dirs. Every source that includes a NITROS header pulls in
# share/isaac_ros_gxf/gxf/include/gxf/core/expected_macro.hpp, whose line 24 is a bare
# `#include "magic_enum.hpp"`, so the build dies with
# `expected_macro.hpp:24: fatal error: magic_enum.hpp: No such file or directory`.
# That bare-name include is ISSUES.md #17; this is the consumer-side half, and it is the
# same two lines scripts/gen_source.py emits for its `magicenum` trait.
export CXXFLAGS="${CXXFLAGS:-} -I${PREFIX}/include/magic_enum"
# CMake seeds CMAKE_CUDA_FLAGS from CUDAFLAGS the way it seeds CMAKE_CXX_FLAGS from
# CXXFLAGS, and nvcc does not otherwise see the C++ one.
export CUDAFLAGS="${CUDAFLAGS:-} -I${PREFIX}/include/magic_enum"

# ament_auto_find_build_dependencies() reads the ament index from the host prefix.
export AMENT_PREFIX_PATH="${PREFIX}${AMENT_PREFIX_PATH:+:${AMENT_PREFIX_PATH}}"
export CMAKE_PREFIX_PATH="${PREFIX}${CMAKE_PREFIX_PATH:+:${CMAKE_PREFIX_PATH}}"

# nvcc comes from ${{ compiler('cuda') }} in build:. This package genuinely needs it --
# alpha_blend.cu.cpp is compiled as CUDA. Set explicitly because the compiler's
# activation script exports CMAKE_ARGS and NVCC_PREPEND_FLAGS but not CUDACXX.
export CUDACXX="${BUILD_PREFIX}/bin/nvcc"

# Build for the architectures Isaac ROS supports (Ampere and newer): 80 (A100),
# 86 (RTX 30xx), 89 (RTX 40xx / Ada), 90 (Hopper), plus PTX for anything later.
CUDA_ARCHS="80;86;89;90"

cmake -S . -B build -G Ninja ${CMAKE_ARGS:-} \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="${PREFIX}" \
  -DCMAKE_PREFIX_PATH="${PREFIX}" \
  -DCMAKE_CUDA_COMPILER="${CUDACXX}" \
  -DCMAKE_CUDA_ARCHITECTURES="${CUDA_ARCHS}" \
  -DPYTHON_EXECUTABLE="${PREFIX}/bin/python" \
  -DBUILD_TESTING=OFF

cmake --build build --parallel "${CPU_COUNT:-2}"
cmake --install build
