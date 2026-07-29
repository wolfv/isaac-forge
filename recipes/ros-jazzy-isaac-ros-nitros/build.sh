#!/usr/bin/env bash
set -euo pipefail

# Fill in the git-lfs pointers from the official deb.
#
# The tarball carries 132-byte LFS pointer files where the vendored SDK binaries
# belong. Replace each pointer *in place* with the real file of the same name from the
# deb payload -- do not restructure the directories. The source tree keeps per-platform
# subdirectories (lib_x86_64_cuda_12_6, lib_x86_64_cuda_13_0, ...) and CMake's install
# rules reference those exact paths, whereas the deb ships a single already-resolved
# copy. Overlaying the deb layout wholesale makes `cmake --install` fail looking for
# lib_x86_64_cuda_12_6/libcuapriltags.a.
STAGE="${SRC_DIR}/_deb"
mkdir -p "${STAGE}"
bsdtar -xOf "${SRC_DIR}/nitros.deb" 'data.tar*' | bsdtar -xf - -C "${STAGE}"

filled=0
unfilled=0
while IFS= read -r ptr; do
  base="$(basename "${ptr}")"
  real="$(find "${STAGE}" -type f -name "${base}" ! -size -1k | head -1)"
  if [ -z "${real}" ]; then
    # Not everything vendored in the repo is shipped in the deb -- the cuMotion
    # python_wheels are an example. Warn rather than fail: if the missing file is
    # actually needed, `cmake --install` says so, and check_blobs.sh independently
    # asserts that the blobs which matter are real ELF rather than pointers.
    echo "WARN no deb replacement for ${ptr#"${SRC_DIR}"/src/isaac_ros_nitros/}"
    unfilled=$((unfilled + 1))
    continue
  fi
  cp -f "${real}" "${ptr}"
  echo "filled $(printf '%-58s' "${ptr#"${SRC_DIR}"/src/isaac_ros_nitros/}") $(stat -c%s "${ptr}") bytes"
  filled=$((filled + 1))
# Scope: only this package's vendored SDK directory, and only this architecture.
# The tarball also contains the sibling isaac_ros_gxf package and aarch64 variants of
# everything, which an amd64 deb cannot supply and which we do not build here.
done < <(grep -rl --binary-files=text 'git-lfs.github.com/spec' \
           "${SRC_DIR}/src/isaac_ros_nitros/lib" 2>/dev/null |
         grep -v aarch64 || true)

if [ "${filled}" -eq 0 ]; then
  echo "no LFS pointers found -- upstream may ship real content now, verify before trusting" >&2
  exit 1
fi
echo "filled ${filled} git-lfs pointer(s) from the deb (${unfilled} left unfilled)"

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
  -DCMAKE_CUDA_ARCHITECTURES="80;86;89;90" \
  -DPYTHON_EXECUTABLE="${PREFIX}/bin/python" \
  -DBUILD_TESTING=OFF

cmake --build build --parallel "${CPU_COUNT:-2}"
cmake --install build

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

rm -rf "${STAGE}"
