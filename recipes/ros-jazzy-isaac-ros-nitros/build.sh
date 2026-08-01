#!/usr/bin/env bash
set -euo pipefail

# Replace the selected architecture's git-lfs pointers with the independently
# SHA256-verified objects fetched by the recipe.
case "${target_platform:-$(uname -m)}" in
  linux-aarch64|aarch64)
    CUVSLAM_DIR=lib_aarch64_jetpack70
    CUAPRILTAGS_DIR=lib_aarch64_jetpack61
    CUMOTION_DIR=aarch64_jetpack70
    ;;
  *)
    CUVSLAM_DIR=lib_x86_64_cuda_13_0
    CUAPRILTAGS_DIR=lib_x86_64_cuda_12_6
    CUMOTION_DIR=x86_64_cuda_13_0
    ;;
esac
NITROS_SRC="${SRC_DIR}/src/isaac_ros_nitros"
cp -f "${SRC_DIR}/blobs/cuvslam/libcuvslam.so" "${NITROS_SRC}/lib/cuvslam/${CUVSLAM_DIR}/libcuvslam.so"
cp -f "${SRC_DIR}/blobs/cuvslam/cuvslam_api_launcher" "${NITROS_SRC}/lib/cuvslam/${CUVSLAM_DIR}/cuvslam_api_launcher"
cp -f "${SRC_DIR}/blobs/cuapriltags/libcuapriltags.a" "${NITROS_SRC}/lib/cuapriltags/${CUAPRILTAGS_DIR}/libcuapriltags.a"
cp -f "${SRC_DIR}/blobs/cumotion/libcumotion.so.1.1.0" "${NITROS_SRC}/lib/cumotion/${CUMOTION_DIR}/lib/libcumotion.so.1.1.0"
for blob in   "${NITROS_SRC}/lib/cuvslam/${CUVSLAM_DIR}/libcuvslam.so"   "${NITROS_SRC}/lib/cuvslam/${CUVSLAM_DIR}/cuvslam_api_launcher"   "${NITROS_SRC}/lib/cuapriltags/${CUAPRILTAGS_DIR}/libcuapriltags.a"   "${NITROS_SRC}/lib/cumotion/${CUMOTION_DIR}/lib/libcumotion.so.1.1.0"; do
  if grep -q --binary-files=text 'git-lfs.github.com/spec' "${blob}"; then
    echo "LFS pointer survived overlay: ${blob}" >&2; exit 1
  fi
done

cd src/isaac_ros_nitros

# GXF's vendored headers include magic_enum by bare filename:
#
#   gxf/core/expected_macro.hpp:24:  #include "magic_enum.hpp"
#
# conda-forge's magic_enum moved its headers into include/magic_enum/ as of 0.9.7, so that
# include stops resolving and every TU pulling in a GXF header fails. The header is
# unmodifiable (it ships inside isaac_ros_gxf as a prebuilt blob) and the include is not
# target-scoped, so the include directory has to be on CXXFLAGS globally rather than come
# from magic_enum's CMake target.
if [ -d "${PREFIX}/include/magic_enum" ]; then
  export CXXFLAGS="${CXXFLAGS:-} -I${PREFIX}/include/magic_enum"
fi

export AMENT_PREFIX_PATH="${PREFIX}${AMENT_PREFIX_PATH:+:${AMENT_PREFIX_PATH}}"
export CMAKE_PREFIX_PATH="${PREFIX}${CMAKE_PREFIX_PATH:+:${CMAKE_PREFIX_PATH}}"
export CUDACXX="${BUILD_PREFIX}/bin/nvcc"

cmake -S . -B build -G Ninja ${CMAKE_ARGS:-} \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="${PREFIX}" \
  -DCMAKE_PREFIX_PATH="${PREFIX}" \
  -DCMAKE_CUDA_COMPILER="${CUDACXX}" \
  -DCMAKE_CUDA_ARCHITECTURES="${CUDA_ARCHITECTURES:-$(case "${target_platform:-$(uname -m)}" in linux-aarch64|aarch64) echo "87;110;120";; *) echo "80;86;89;90";; esac)}" \
  -DPYTHON_EXECUTABLE="${PREFIX}/bin/python" \
  -DBUILD_TESTING=OFF

cmake --build build --parallel "${CPU_COUNT:-2}"
cmake --install build

# cuVSLAM's public header uses uint8_t/uint32_t without including <cstdint>. Patch the
# installed SDK header once so every downstream consumer gets a self-contained header.
# The header carries NVIDIA's Open Software License, which permits modification.
CUVSLAM_H="${PREFIX}/share/isaac_ros_nitros/cuvslam/include/cuvslam/cuvslam2.h"
if [ ! -f "${CUVSLAM_H}" ]; then
  echo "expected cuVSLAM header at ${CUVSLAM_H}; installed layout changed" >&2
  exit 1
fi
if ! grep -q '#include <cstdint>' "${CUVSLAM_H}"; then
  sed -i '0,/#include <array>/s//#include <array>\n#include <cstdint>/' "${CUVSLAM_H}"
fi
grep -q '#include <cstdint>' "${CUVSLAM_H}" || {
  echo "failed to add <cstdint> to ${CUVSLAM_H}" >&2; exit 1; }

# Drop the Eigen 3 floor from NVIDIA's cuMotion CMake config -- ISSUES.md #13.
#
# cumotionConfig.cmake opens with `find_dependency(Eigen3 3.3)`. Eigen's own Eigen3Config
# declares SameMajorVersion compatibility, so that request *rejects* the eigen 5.0.1 that
# robostack-jazzy is built against, and every cuMotion consumer fails to configure:
#
#   Could not find a configuration file for package "Eigen3" that is compatible
#   with requested version "3.3".
#     $PREFIX/share/eigen3/cmake/Eigen3Config.cmake, version: 5.0.1
#
# The constraint is stricter than the ABI needs. What crosses into libcumotion.so is
# Eigen::Matrix<double,3,1,0,3,1> and Eigen::Quaternion<double,0> by const reference --
# same template signature and same layout in eigen 3 and 5, which is why the symbols link
# at all. Built this way, cuMotion's IK lands 0.000 mm from the requested pose; see
# manip/fk_check.py. Removing the floor is what lets isaac_ros_cumotion_moveit exist,
# because moveit_core is eigen 5.
#
# Patched here rather than in each consumer so it holds for anything that finds cuMotion,
# now or later. The file carries an Apache-2.0 SPDX header, so this is ours to change.
CUMOTION_CONFIG="${PREFIX}/share/isaac_ros_nitros/cumotion/lib/cmake/cumotion/cumotionConfig.cmake"
if ! grep -q 'find_dependency(Eigen3 3\.3)' "${CUMOTION_CONFIG}"; then
  echo "cumotionConfig.cmake no longer pins Eigen3 3.3 -- re-read ISSUES.md #13 before" >&2
  echo "dropping this patch; upstream may have fixed it, or moved the constraint." >&2
  exit 1
fi
sed -i 's/find_dependency(Eigen3 3\.3)/find_dependency(Eigen3)  # version floor removed, see isaac-forge ISSUES.md #13/' \
  "${CUMOTION_CONFIG}"
echo "patched cumotionConfig.cmake: find_dependency(Eigen3 3.3) -> find_dependency(Eigen3)"
