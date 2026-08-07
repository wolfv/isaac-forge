#!/usr/bin/env bash
# Repack NVIDIA's native CPython binding without modifying its extension module.
set -euo pipefail

STAGE="${SRC_DIR}/stage"
mkdir -p "${STAGE}" "${SP_DIR}"

# Debian packages are ar archives containing a data tarball.
bsdtar -xOf "${SRC_DIR}/python3-libnvinfer.deb" 'data.*' | \
  bsdtar -xf - -C "${STAGE}"

DEB_SITE="${STAGE}/usr/lib/python3.12/dist-packages"
test -d "${DEB_SITE}/tensorrt" || {
  echo "python3-libnvinfer does not contain the CPython 3.12 tensorrt module"
  exit 1
}

cp -a "${DEB_SITE}/." "${SP_DIR}/"

# Verify the copy before making the one required conda adaptation. Debian puts TensorRT
# in the system loader path; conda puts it in ${PREFIX}/lib. An old-style RPATH is used
# deliberately because it is inherited while libnvinfer loads its CUDA dependencies.
installed="${SP_DIR}/tensorrt/tensorrt.so"
original="${DEB_SITE}/tensorrt/tensorrt.so"
test -f "${installed}"
cmp -s "${installed}" "${original}" || {
  echo "FAIL: tensorrt.so changed before RPATH installation"
  exit 1
}
patchelf --force-rpath --set-rpath '$ORIGIN:$ORIGIN/../../..' "${installed}"
patchelf --print-rpath "${installed}" | grep -Fx '$ORIGIN:$ORIGIN/../../..'

# The deb and wheel both carry the TensorRT license alongside the Python distribution.
license="$(find "${DEB_SITE}" -path '*.dist-info/LICENSE.txt' -print -quit)"
test -n "${license}" || { echo "TensorRT Python license is missing"; exit 1; }
cp "${license}" "${SRC_DIR}/LICENSE"

echo "TensorRT ${PKG_VERSION} Python bindings repacked for $(uname -m)"
file "${installed}"
