#!/usr/bin/env bash
set -euo pipefail

# Build only the isaac_ros_visual_slam package. The repo also contains
# isaac_ros_visual_slam_interfaces, but that one is repacked from NVIDIA's deb --
# its rosidl typesupport is ABI-compatible with RoboStack's (see FINDINGS.md §5),
# and repacking avoids regenerating message code here.
# rattler-build strips the archive top-level dir, so contents land in src/.
cd src/isaac_ros_visual_slam

# ament_auto_find_build_dependencies() and ament_index_get_resource() both read the
# ament index, so the host prefix has to be on AMENT_PREFIX_PATH. In particular
# this is how CMakeLists.txt locates cuVSLAM:
#
#   ament_index_get_resource(CUVSLAM_RELATIVE_PATH cuvslam isaac_ros_nitros)
#
# which resolves to $PREFIX/share/isaac_ros_nitros/cuvslam from our repack.
export AMENT_PREFIX_PATH="${PREFIX}${AMENT_PREFIX_PATH:+:${AMENT_PREFIX_PATH}}"
export CMAKE_PREFIX_PATH="${PREFIX}${CMAKE_PREFIX_PATH:+:${CMAKE_PREFIX_PATH}}"

# No -include cstdint workaround needed: ros-jazzy-isaac-ros-nitros patches the
# missing #include <cstdint> into cuvslam2.h when it repacks the header, so the
# header we compile against is self-contained. See POST_FIXUP in
# scripts/gen_repack.py and ISSUES.md #1.

cmake -S . -B build -G Ninja ${CMAKE_ARGS:-} \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="${PREFIX}" \
  -DCMAKE_PREFIX_PATH="${PREFIX}" \
  -DPYTHON_EXECUTABLE="${PREFIX}/bin/python" \
  -DBUILD_TESTING=OFF

cmake --build build --parallel "${CPU_COUNT:-2}"
cmake --install build

# CMakeLists.txt copies cuVSLAM's runtime into lib/ as a convenience:
#
#   install(FILES ${CUVSLAM}/lib/libcuvslam.so DESTINATION lib)
#   install(PROGRAMS ${CUVSLAM}/lib/cuvslam_api_launcher DESTINATION lib/...)
#
# ros-jazzy-isaac-ros-nitros already ships both, so keeping them here would make
# two packages own the same files. Drop our copies and let nitros own them.
rm -f "${PREFIX}/lib/libcuvslam.so"
rm -f "${PREFIX}/lib/isaac_ros_visual_slam/cuvslam_api_launcher"

# Point the node at nitros's copy of cuVSLAM rather than the one we just deleted.
for so in "${PREFIX}/lib/libvisual_slam_node.so" \
          "${PREFIX}/lib/isaac_ros_visual_slam/isaac_ros_visual_slam"; do
  [ -f "${so}" ] || continue
  old="$(patchelf --print-rpath "${so}" 2>/dev/null || true)"
  case "${so}" in
    */lib/*/*) up=".." ;;   # one level below lib/
    *)         up="." ;;
  esac
  new="\$ORIGIN:\$ORIGIN/${up}:\$ORIGIN/${up}/../share/isaac_ros_nitros/cuvslam/lib"
  patchelf --set-rpath "${new}${old:+:${old}}" "${so}"
  echo "rpath ${so#"${PREFIX}"/}: ${new}"
done
