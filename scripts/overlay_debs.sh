#!/usr/bin/env bash
# Overlay Isaac ROS debs onto a conda/pixi prefix.
#
# This is the prototype of what the per-package repack recipes do: the debs lay
# their payload out under /opt/ros/jazzy/{lib,share,include}, which maps directly
# onto a conda prefix once that leading path is stripped.
#
# Usage: overlay_debs.sh <prefix> <deb> [<deb> ...]
set -euo pipefail

PREFIX="$1"; shift
[ -d "${PREFIX}" ] || { echo "no such prefix: ${PREFIX}" >&2; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "${STAGE}"' EXIT

for deb in "$@"; do
  bsdtar -xOf "${deb}" 'data.tar*' | bsdtar -xf - -C "${STAGE}"
done

if [ ! -d "${STAGE}/opt/ros/jazzy" ]; then
  echo "unexpected deb layout: no opt/ros/jazzy" >&2
  find "${STAGE}" -maxdepth 3 -type d >&2
  exit 1
fi

# Some debs (e.g. ros-jazzy-negotiated) install into the Debian multiarch
# subdirectory lib/x86_64-linux-gnu/ rather than lib/. A conda prefix has no
# multiarch layer, and the loader will not search that subdir, so flatten it
# before merging.
if [ -d "${STAGE}/opt/ros/jazzy/lib/x86_64-linux-gnu" ]; then
  cp -a "${STAGE}/opt/ros/jazzy/lib/x86_64-linux-gnu/." "${STAGE}/opt/ros/jazzy/lib/"
  rm -rf "${STAGE}/opt/ros/jazzy/lib/x86_64-linux-gnu"
fi

# Merge opt/ros/jazzy/* into the prefix. -a keeps symlinks and modes; the
# trailing /. copies contents rather than the directory itself.
cp -a "${STAGE}/opt/ros/jazzy/." "${PREFIX}/"

# A few debs ship payload outside the ROS tree.
for extra in usr/lib/x86_64-linux-gnu usr/lib usr/include; do
  if [ -d "${STAGE}/${extra}" ]; then
    case "${extra}" in
      *include) cp -a "${STAGE}/${extra}/." "${PREFIX}/include/" ;;
      *)        cp -a "${STAGE}/${extra}/." "${PREFIX}/lib/" ;;
    esac
  fi
done

# NVIDIA SDK-style debs (cvcuda, VPI, ...) use /opt/nvidia/<sdk>/{lib,include},
# sometimes with a lib/x86_64-linux-gnu multiarch level underneath.
for sdk in "${STAGE}"/opt/nvidia/*/; do
  [ -d "${sdk}" ] || continue
  for sub in lib lib/x86_64-linux-gnu lib64; do
    if [ -d "${sdk}${sub}" ] && [ ! -L "${sdk}${sub}" ]; then
      find "${sdk}${sub}" -maxdepth 1 \( -type f -o -type l \) -name '*.so*' \
        -exec cp -a {} "${PREFIX}/lib/" \;
    fi
  done
  [ -d "${sdk}include" ] && cp -a "${sdk}include/." "${PREFIX}/include/"
done

echo "overlaid $# deb(s) onto ${PREFIX}"
