#!/usr/bin/env bash
# Repack NVIDIA's TensorRT debs. See recipe.yaml for why debs rather than the tarball,
# and why 10.13.3.9+cuda13.0 rather than the 10.9.0.34+cuda12.8 Isaac ROS 4.5 ships
# against.
set -euo pipefail

STAGE="${SRC_DIR}/stage"
mkdir -p "${STAGE}" "${PREFIX}/lib" "${PREFIX}/include"

# The debs are `ar` archives holding a compressed data tarball. bsdtar reads both layers,
# which is why libarchive is a build requirement.
for deb in libnvinfer10 libnvinfer-plugin10 libnvonnxparsers10 \
           libnvinfer-headers-dev libnvinfer-headers-plugin-dev libnvonnxparsers-dev; do
  test -f "${SRC_DIR}/${deb}.deb" || { echo "missing source: ${deb}.deb"; exit 1; }
  bsdtar -xOf "${SRC_DIR}/${deb}.deb" 'data.*' | bsdtar -xf - -C "${STAGE}"
done

DEBLIB=""
for candidate in "${STAGE}"/usr/lib/*-linux-gnu; do
  if [ -d "${candidate}" ]; then DEBLIB="${candidate}"; break; fi
done
DEBINC=""
for candidate in "${STAGE}"/usr/include/*-linux-gnu; do
  if [ -d "${candidate}" ]; then DEBINC="${candidate}"; break; fi
done
[ -n "${DEBLIB}" ] || { echo "TensorRT deb has no multiarch library directory"; exit 1; }
[ -n "${DEBINC}" ] || { echo "TensorRT deb has no multiarch include directory"; exit 1; }

# Shared objects and their soname symlinks, copied with -a so the symlinks stay symlinks
# rather than becoming six more copies of a 1.3 GB file.
cp -a "${DEBLIB}"/*.so* "${PREFIX}/lib/"

# Static archives are not wanted: libnvonnxparsers-dev carries libnvonnxparser_static.a
# and libonnx_proto.a, nothing here links statically, and they are pure weight in a
# package that is already large.
rm -f "${PREFIX}/lib"/*.a

# Headers. All three dev debs put them in the same multiarch directory.
cp -a "${DEBINC}"/*.h "${PREFIX}/include/"

# The bare .so symlinks that CMake needs, and the reason this recipe does not simply
# install the -dev debs.
#
# FindTENSORRT.cmake (in isaac_ros_common) resolves the libraries with
#     find_library(TENSORRT_${libname}_LIBRARY NAMES ${libname} REQUIRED)
# and find_library matches CMAKE_FIND_LIBRARY_SUFFIXES -- `.so`, not `.so.10`. So a
# prefix holding only the runtime debs' `libnvinfer.so.10` and `libnvinfer.so.10.13.3`
# fails to configure isaac_ros_tensor_rt even though the library is right there.
#
# Upstream ships those symlinks in the -dev packages, but libnvinfer-dev is 2.5 GB of
# static archives for two symlinks, so create them instead. A symlink to the soname is
# exactly what the -dev deb contains -- checked against libnvonnxparsers-dev, which we do
# install and which ships `libnvonnxparser.so -> libnvonnxparser.so.10`.
for lib in nvinfer nvinfer_plugin nvonnxparser; do
  if [ ! -e "${PREFIX}/lib/lib${lib}.so" ]; then
    soname="$(cd "${PREFIX}/lib" && ls -1 "lib${lib}.so."[0-9]* 2>/dev/null | sort -V | head -1)"
    test -n "${soname}" || { echo "no versioned lib${lib}.so.* to link"; exit 1; }
    ln -s "${soname}" "${PREFIX}/lib/lib${lib}.so"
    echo "  linked lib${lib}.so -> ${soname}"
  fi
done

# NVIDIA's license text, which the debs install per-package under share/doc. They are all
# the same TensorRT terms; take one for `license_file` and keep the rest where they are.
cp "${STAGE}/usr/share/doc/libnvinfer10/copyright" "${SRC_DIR}/LICENSE"

# Nothing above patches a binary, and `binary_relocation: false` in the recipe keeps
# rattler-build from doing it either -- so what ships is byte-for-byte NVIDIA's. Assert
# that rather than trust it: a silent relink would change the RPATH of a library whose
# whole value is being the binary NVIDIA tested.
for f in libnvinfer.so.10 libnvinfer_plugin.so.10 libnvonnxparser.so.10; do
  real="$(readlink -f "${PREFIX}/lib/${f}")"
  orig="${DEBLIB}/$(basename "${real}")"
  cmp -s "${real}" "${orig}" || { echo "FAIL: ${f} differs from the NVIDIA source payload"; exit 1; }
done
echo "  verified: shared objects are byte-identical to the NVIDIA source payload"

# Do not infer GPU support from a Jetson repository name. Match the pinned r39.2
# runtime deb, then verify native SM87 SASS in both CUDA-bearing libraries.
ORIN_DEB_SHA256="d02111e3600d91bef407fe537a4179445cdc73fb259bf1f83dd256804de1897e"
is_orin=0
if [ "$(sha256sum "${SRC_DIR}/libnvinfer10.deb" | awk '{print $1}')" = "${ORIN_DEB_SHA256}" ]; then
  is_orin=1
  for lib in libnvinfer.so.10 libnvinfer_plugin.so.10; do
    cuobjdump --list-elf "${PREFIX}/lib/${lib}" > "${SRC_DIR}/${lib}.elf-list"
    grep -q 'sm_87.cubin' "${SRC_DIR}/${lib}.elf-list" || {
      echo "FAIL: ${lib} has no native SM87 cubin"; exit 1;
    }
  done
  echo "  verified: runtime and plugin contain native SM87 SASS"
fi

# Builder resources are dlopen'd rather than linked, so confirm they arrived. TensorRT
# 10.13 uses one monolithic file; 10.16 splits it by GPU family plus a PTX fallback.
if [ "${is_orin}" = 1 ]; then
  test -f "${PREFIX}/lib/libnvinfer_builder_resource_sm86.so.10.16.2" || {
    echo "FAIL: Orin builder resource missing"; exit 1; }
  test -f "${PREFIX}/lib/libnvinfer_builder_resource_ptx.so.10.16.2" || {
    echo "FAIL: PTX builder resource missing"; exit 1; }
else
  ls -1 "${PREFIX}/lib"/libnvinfer_builder_resource.so.* >/dev/null || {
    echo "FAIL: libnvinfer_builder_resource.so.* missing"; exit 1; }
fi

# The Windows builder resource ships in its own deb (libnvinfer-win-builder-resource10),
# which this recipe does not fetch -- assert it did not arrive by another route, since it
# would be a gigabyte of dead weight.
! ls "${PREFIX}/lib"/libnvinfer_builder_resource_win.so.* >/dev/null 2>&1 || {
  echo "FAIL: Windows builder resource present"; exit 1; }

rm -rf "${STAGE}"
echo "TensorRT ${PKG_VERSION} repacked:"
ls -la "${PREFIX}/lib"/libnv*.so.* | awk '{printf "  %8.1f MB  %s\n", $5/1048576, $9}'
