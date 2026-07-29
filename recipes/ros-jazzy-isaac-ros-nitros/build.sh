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

rm -rf "${STAGE}"
