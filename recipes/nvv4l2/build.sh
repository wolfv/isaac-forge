#!/usr/bin/env bash
set -euo pipefail

# Unpack the official Isaac ROS deb into the conda prefix.
#
# The debs use three layouts, all of which appear in the closure:
#   opt/ros/jazzy/{lib,share,include}      the ROS tree
#   opt/ros/jazzy/lib/x86_64-linux-gnu     Debian multiarch (e.g. negotiated)
#   opt/nvidia/<sdk>/lib                   NVIDIA SDK style (cvcuda, VPI)
STAGE="${SRC_DIR}/_stage"
mkdir -p "${STAGE}" "${PREFIX}/lib"
# One conda package can repack several debs -- e.g. libcvcuda comes from both
# libcvcuda0 (runtime .so) and cvcuda0-dev (the cvcuda/ and nvcv/ headers that
# isaac_ros_image_proc includes).
for deb in "${SRC_DIR}"/pkg*.deb; do
  bsdtar -xOf "${deb}" 'data.tar*' | bsdtar -xf - -C "${STAGE}"
done

# Flatten the Debian multiarch level into lib/ so the loader finds these without
# an extra search path -- but leave a symlink behind at the original location.
# The debs' generated CMake exports reference
# ${_IMPORT_PREFIX}/lib/x86_64-linux-gnu/<lib>, and those files have an EXISTS
# assertion that hard-fails configure if the path is gone (ros-jazzy-negotiated).
MULTIARCH="${STAGE}/opt/ros/jazzy/lib/x86_64-linux-gnu"
if [ -d "${MULTIARCH}" ]; then
  for f in "${MULTIARCH}"/*; do
    [ -e "${f}" ] || continue
    base="$(basename "${f}")"
    cp -a "${f}" "${STAGE}/opt/ros/jazzy/lib/${base}"
    rm -rf "${f}"
    ln -s "../${base}" "${MULTIARCH}/${base}"
  done
fi

# Note: written as if-blocks rather than `[ -d X ] && cp ...`, because under
# `set -e` that idiom aborts the script when the directory is simply absent --
# which is the normal case for the non-ROS SDK debs (libcvcuda, VPI).
if [ -d "${STAGE}/opt/ros/jazzy" ]; then
  cp -a "${STAGE}/opt/ros/jazzy/." "${PREFIX}/"
fi

for sdk in "${STAGE}"/opt/nvidia/*/; do
  [ -d "${sdk}" ] || continue
  for sub in lib lib/x86_64-linux-gnu lib64; do
    if [ -d "${sdk}${sub}" ] && [ ! -L "${sdk}${sub}" ]; then
      find "${sdk}${sub}" -maxdepth 1 \( -type f -o -type l \) -name '*.so*' \
        -exec cp -a {} "${PREFIX}/lib/" \;
    fi
  done
  if [ -d "${sdk}include" ]; then
    mkdir -p "${PREFIX}/include"
    cp -a "${sdk}include/." "${PREFIX}/include/"
  fi
done

for extra in usr/lib/x86_64-linux-gnu usr/lib; do
  if [ -d "${STAGE}/${extra}" ]; then
    mkdir -p "${PREFIX}/lib"
    cp -a "${STAGE}/${extra}/." "${PREFIX}/lib/"
  fi
done
if [ -d "${STAGE}/usr/include" ]; then
  mkdir -p "${PREFIX}/include"
  cp -a "${STAGE}/usr/include/." "${PREFIX}/include/"
fi

rm -rf "${STAGE}"

# Rewrite /opt/ros/jazzy to the build prefix in text files.
#
# The debs bake absolute paths into more than just RUNPATHs. The ament resource
# index is the one that bites first: share/ament_index/resource_index/
# isaac_ros_common_cmake_path/isaac_ros_common contains the literal string
# /opt/ros/jazzy/share/isaac_ros_common/cmake, and every Isaac CMakeLists does
#
#   ament_index_get_resource(ISAAC_ROS_COMMON_CMAKE_PATH isaac_ros_common_cmake_path isaac_ros_common)
#   include("${ISAAC_ROS_COMMON_CMAKE_PATH}/isaac_ros_common-version-info.cmake")
#
# which hard-fails when that path does not exist. The same applies to generated
# .cmake exports and the ament environment hooks.
#
# Writing ${PREFIX} literally is the right move in conda: rattler-build detects
# the build prefix in text files and rewrites it to the install prefix when the
# package is unpacked. grep -I skips binaries, which patchelf handles instead.
mapfile -t textfiles < <(grep -rIl '/opt/ros/jazzy' "${PREFIX}" 2>/dev/null || true)
if [ "${#textfiles[@]}" -gt 0 ]; then
  printf 'rewriting /opt/ros/jazzy -> $PREFIX in %d text files\n' "${#textfiles[@]}"
  for f in "${textfiles[@]}"; do
    sed -i "s|/opt/ros/jazzy|${PREFIX}|g" "${f}"
  done
fi

# Rewrite absolute RUNPATHs to $ORIGIN-relative ones.
#
# The debs bake in paths like /opt/ros/jazzy/share/isaac_ros_gxf/gxf/lib/std and
# /usr/local/cuda/lib64, which do not exist in a conda prefix. Since the tree
# layout under $PREFIX matches the layout under /opt/ros/jazzy, each entry maps
# cleanly onto $ORIGIN plus the right number of ".." hops for that file's depth.
python "${RECIPE_DIR}/relink.py" "${PREFIX}"

# --- package-specific fixup (see POST_FIXUP in scripts/gen_repack.py) ---
PLUGIN_DIR="${PREFIX}/lib/libv4l/plugins"
mkdir -p "${PLUGIN_DIR}"
moved=0
for p in "${PREFIX}"/lib/*v4l2_plugin.so; do
  [ -f "${p}" ] || continue
  mv "${p}" "${PLUGIN_DIR}/"
  echo "moved $(basename "${p}") into lib/libv4l/plugins/"
  moved=$((moved + 1))
done
if [ "${moved}" -eq 0 ]; then
  echo "no *v4l2_plugin.so found -- layout changed, check POST_FIXUP" >&2
  exit 1
fi

# The deb payload lands both flat and under a multiarch subdir; drop the duplicate.
rm -rf "${PREFIX}/lib/x86_64-linux-gnu"
