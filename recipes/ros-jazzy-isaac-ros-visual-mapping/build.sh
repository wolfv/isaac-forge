#!/usr/bin/env bash
set -euo pipefail

# One script, both outputs. It unpacks the deb, normalises the payload, and then installs
# the subset that belongs to $PKG_NAME. Sharing the script keeps the normalisation in one
# place -- the two outputs must agree about what the tree looks like, because the ament
# index and the CMake exports in the base package describe paths the tools output fills in.

STAGE="${SRC_DIR}/_stage"
rm -rf "${STAGE}"
mkdir -p "${STAGE}"
bsdtar -xOf "${SRC_DIR}/visual_mapping.deb" 'data.tar*' | bsdtar -xf - -C "${STAGE}"

ROOT="${STAGE}/opt/ros/jazzy"
[ -d "${ROOT}" ] || { echo "expected ${ROOT} -- deb layout changed" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Absolute paths baked into text files
# ---------------------------------------------------------------------------
# Three rewrites, each asserted before and after, because all three fail silently at build
# time and loudly in somebody else's configure step.

# (a) /opt/ros/jazzy -> ${PREFIX}. The ament resource index, the generated CMake exports
# and the environment hooks all carry it. Writing ${PREFIX} literally is correct in conda:
# rattler-build detects the build prefix in text files and rewrites it on install.
mapfile -t rospaths < <(grep -rIl '/opt/ros/jazzy' "${ROOT}" 2>/dev/null || true)
[ "${#rospaths[@]}" -gt 0 ] || {
  echo "no file names /opt/ros/jazzy -- the deb no longer targets it, check this script" >&2
  exit 1; }
printf 'rewriting /opt/ros/jazzy -> $PREFIX in %d files\n' "${#rospaths[@]}"
for f in "${rospaths[@]}"; do
  sed -i "s|/opt/ros/jazzy|${PREFIX}|g" "${f}"
done

# (b) /usr/include/eigen3 and /usr/include/opencv4, which appear in
# INTERFACE_INCLUDE_DIRECTORIES on the imported targets of *both* export sets:
#
#   share/visual_mapping/cmake/visual_mappingTargets.cmake
#   share/isaac_ros_visual_mapping/cmake/export_isaac_ros_visual_mappingExport.cmake
#
# CMake rejects a non-existent include directory on an imported target outright --
# "imported target ... includes non-existent path" -- so leaving these would break every
# consumer's configure, not just degrade it. Same failure class as the BUILD_PREFIX leak
# the nvblox recipes guard against.
#
# The substitution is a real fix rather than a way to quiet the check: conda-forge puts
# Eigen's headers in include/eigen3 and OpenCV's in include/opencv4, exactly the layout
# Debian uses, so the same relative path holds under ${PREFIX}.
for hostdir in eigen3 opencv4; do
  mapfile -t hits < <(grep -rIl "/usr/include/${hostdir}" "${ROOT}" 2>/dev/null || true)
  [ "${#hits[@]}" -gt 0 ] || {
    echo "expected /usr/include/${hostdir} in the CMake exports and found none --" >&2
    echo "upstream may have fixed it; drop this rewrite rather than skipping it" >&2
    exit 1; }
  printf 'rewriting /usr/include/%s -> $PREFIX/include/%s in %d files\n' \
    "${hostdir}" "${hostdir}" "${#hits[@]}"
  for f in "${hits[@]}"; do
    sed -i "s|/usr/include/${hostdir}|${PREFIX}/include/${hostdir}|g" "${f}"
  done
done

# Nothing may still name a build-machine directory. Scoped to the three strings rewritten
# above rather than to /usr/include in general: common/geometry/math_utils.h cites
# /usr/include/bits/mathinline.h in a comment about i386 FPU intrinsics, which is prose
# about glibc and not a path anything resolves.
left=$(grep -rIl -e '/usr/include/eigen3' -e '/usr/include/opencv4' -e '/opt/ros/' \
         "${ROOT}" 2>/dev/null | head -5 || true)
if [ -n "${left}" ]; then
  echo "FAIL: build-machine paths remain:" >&2
  echo "${left}" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. The deb ships its headers and its static libraries twice
# ---------------------------------------------------------------------------
# Not a mistake to clean up -- both copies are load-bearing, because the deb carries two
# independent CMake export sets that disagree about where things live:
#
#   visual_mapping::*              lib/x86_64-linux-gnu/visual_mapping/*.a   include/visual_mapping
#   isaac_ros_visual_mapping::*    lib/*.a                                   include
#
# and each export ends with a foreach that FATAL_ERRORs if an IMPORTED_LOCATION does not
# exist. So both paths have to resolve. Verified byte-identical (all 4 archives, all 12
# header subtrees), so one real copy plus symlinks satisfies both exports at half the size:
# 20 MB of archives and 5.5 MB of headers stop being duplicated.
#
# Chosen direction: the flat paths stay real. lib/*.a and include/<subtree> are the
# conventional conda locations, and they are what the ament export -- the one a ROS
# consumer reaches through find_package(isaac_ros_visual_mapping) -- names.

dedupe_to_symlink() {
  # $1 real path, $2 duplicate path, $3 relative target from $2's directory
  cmp -s "$1" "$2" || {
    echo "expected $2 to duplicate $1 and it does not -- do not symlink" >&2; exit 1; }
  rm -rf "$2"
  ln -s "$3" "$2"
}

MULTIARCH="${ROOT}/lib/x86_64-linux-gnu/visual_mapping"
[ -d "${MULTIARCH}" ] || { echo "expected ${MULTIARCH}" >&2; exit 1; }
n=0
for a in "${MULTIARCH}"/*.a; do
  base="$(basename "${a}")"
  dedupe_to_symlink "${ROOT}/lib/${base}" "${a}" "../../${base}"
  n=$((n + 1))
done
echo "deduped ${n} static archives under lib/x86_64-linux-gnu/visual_mapping/"

# Headers: include/visual_mapping/<subtree> -> ../<subtree>. `diff -rq` rather than `cmp`
# because these are trees.
n=0
for d in "${ROOT}"/include/visual_mapping/*; do
  [ -d "${d}" ] || continue
  base="$(basename "${d}")"
  diff -rq "${ROOT}/include/${base}" "${d}" >/dev/null || {
    echo "include/${base} and include/visual_mapping/${base} differ -- do not symlink" >&2
    exit 1; }
  rm -rf "${d}"
  ln -s "../${base}" "${d}"
  n=$((n + 1))
done
[ "${n}" -gt 0 ] || { echo "no header subtrees found under include/visual_mapping" >&2; exit 1; }
echo "deduped ${n} header subtrees under include/visual_mapping/"

# Executables: 12 of the 16 in bin/visual_mapping are byte-identical to their counterparts
# in lib/isaac_ros_visual_mapping. Safe to symlink because both directories sit two levels
# under the prefix, so relink.py gives them the same $ORIGIN-relative RUNPATH either way --
# and the loader takes $ORIGIN from the resolved path anyway.
n=0
for f in "${ROOT}"/bin/visual_mapping/*; do
  [ -f "${f}" ] || continue
  base="$(basename "${f}")"
  target="${ROOT}/lib/isaac_ros_visual_mapping/${base}"
  [ -f "${target}" ] && cmp -s "${f}" "${target}" || continue
  rm -f "${f}"
  ln -s "../../lib/isaac_ros_visual_mapping/${base}" "${f}"
  n=$((n + 1))
done
echo "deduped ${n} executables under bin/visual_mapping/"

# ---------------------------------------------------------------------------
# 3. Install the subset this output owns
# ---------------------------------------------------------------------------
case "${PKG_NAME}" in
  ros-jazzy-isaac-ros-visual-mapping)
    # Headers, the four archives at both paths, both CMake export sets, the ament index,
    # the .pb.txt configs and the ONNX weights. No ELF content at all.
    mkdir -p "${PREFIX}/include" "${PREFIX}/lib" "${PREFIX}/share" "${PREFIX}/bin"
    cp -a "${ROOT}/include/." "${PREFIX}/include/"
    cp -a "${ROOT}/share/." "${PREFIX}/share/"
    cp -a "${ROOT}"/lib/*.a "${PREFIX}/lib/"
    mkdir -p "${PREFIX}/lib/x86_64-linux-gnu"
    cp -a "${ROOT}/lib/x86_64-linux-gnu/visual_mapping" "${PREFIX}/lib/x86_64-linux-gnu/"
    # The generated python protobuf bindings the deb puts in bin/. Kept because
    # cusfm_cli and create_cuvgl_map.py import them, and dropped from the tools output so
    # only one package owns them.
    cp -a "${ROOT}/bin/python_protos" "${PREFIX}/bin/"
    # Guard against shipping an ELF file from the wrong output.
    found=$(find "${PREFIX}" -type f -exec sh -c 'head -c4 "$1" | grep -q ELF' _ {} \; -print | head -3)
    [ -z "${found}" ] || { echo "FAIL: ELF files in the base output: ${found}" >&2; exit 1; }
    echo "installed the library/header/model output"
    ;;

  ros-jazzy-isaac-ros-visual-mapping-tools)
    mkdir -p "${PREFIX}/bin" "${PREFIX}/lib"
    cp -a "${ROOT}/lib/isaac_ros_visual_mapping" "${PREFIX}/lib/"
    cp -a "${ROOT}/bin/visual_mapping" "${PREFIX}/bin/"

    # Rewrite absolute RUNPATHs to $ORIGIN-relative ones.
    #
    # The tools arrive with RUNPATH ":/lib" -- an empty entry, which means the current
    # working directory, and then the *system* /lib. Neither is any use in a conda prefix;
    # on Ubuntu these binaries are found by LD_LIBRARY_PATH from the ament environment
    # hook. relink.py drops both and substitutes $ORIGIN-relative entries, so no
    # activation hook is needed.
    python "${RECIPE_DIR}/relink.py" "${PREFIX}"

    # cuvslam_api_launcher is the one binary the generic rules do not cover. It sits in
    # .../visual_mapping/bin and NEEDs libcuvslam.so from .../visual_mapping/lib -- a
    # sibling directory, not $PREFIX/lib -- and its shipped RUNPATH points at
    # /cuvslam/build/bin, a path inside NVIDIA's build container. relink.py adds the
    # sibling rule; this asserts it worked, because the failure is a dlopen error at first
    # use and nothing earlier would notice.
    LAUNCHER="${PREFIX}/lib/isaac_ros_visual_mapping/visual_mapping/bin/cuvslam_api_launcher"
    [ -f "${LAUNCHER}" ] || { echo "cuvslam_api_launcher missing" >&2; exit 1; }
    if ldd "${LAUNCHER}" 2>/dev/null | grep -q 'libcuvslam.so.*not found'; then
      echo "FAIL: cuvslam_api_launcher cannot resolve libcuvslam.so" >&2
      patchelf --print-rpath "${LAUNCHER}" >&2
      exit 1
    fi
    echo "cuvslam_api_launcher resolves libcuvslam.so"
    ;;

  *)
    echo "unexpected PKG_NAME ${PKG_NAME}" >&2
    exit 1
    ;;
esac

rm -rf "${STAGE}"
