# Isaac ROS GXF loader path.
#
# The Isaac debs hard-code absolute RUNPATHs such as
#   /opt/ros/jazzy/share/isaac_ros_gxf/gxf/lib/std
# which do not exist inside a conda prefix, and the GXF core and extension
# libraries live in nested share/**/gxf/lib directories rather than in lib/.
#
# Prepending those directories to LD_LIBRARY_PATH is the least invasive fix for a
# demo overlay. Proper repack recipes should instead rewrite the RPATH to
# $ORIGIN-relative paths at package build time, so this hook is not needed.

_isaac_gxf_dirs="$(
  find "${CONDA_PREFIX}/share" -name '*.so' -path '*gxf*' -printf '%h\n' 2>/dev/null |
    sort -u | tr '\n' ':'
)"

if [ -n "${_isaac_gxf_dirs}" ]; then
  export ISAAC_GXF_LD_LIBRARY_PATH_BACKUP="${LD_LIBRARY_PATH:-}"
  export LD_LIBRARY_PATH="${_isaac_gxf_dirs}${LD_LIBRARY_PATH:-}"
fi
unset _isaac_gxf_dirs
