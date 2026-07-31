#!/usr/bin/env bash
set -euo pipefail

# Libraries only. The Qt GUIs and the DVB stack would drag in qt6 and a large
# dependency tree for tools nobody asked for yet; enable them in the feedstock if
# that changes.
meson setup builddir \
  --prefix="${PREFIX}" \
  --libdir=lib \
  --buildtype=release \
  -Dv4l-utils=false \
  -Dqv4l2=disabled \
  -Dqvidcap=disabled \
  -Dlibdvbv5=disabled \
  -Dv4l2-tracer=disabled \
  -Dbpf=disabled \
  -Dgconv=disabled \
  -Djpeg=enabled \
  -Dv4l-plugins=true \
  -Dv4l-wrappers=true

meson compile -C builddir -j "${CPU_COUNT:-2}"
meson install -C builddir --no-rebuild
