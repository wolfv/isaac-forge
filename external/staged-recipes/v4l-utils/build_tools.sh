#!/usr/bin/env bash
set -euo pipefail

# CLI tools. The libraries come from the libv4l output, so this build only adds
# the executables; meson still needs the library targets configured, so the same
# feature flags are passed and the duplicate library files are removed afterwards.
meson setup builddir \
  --prefix="${PREFIX}" \
  --libdir=lib \
  --buildtype=release \
  -Dv4l-utils=true \
  -Dqv4l2=disabled \
  -Dqvidcap=disabled \
  -Dlibdvbv5=disabled \
  -Dv4l2-tracer=disabled \
  -Dbpf=disabled \
  -Dgconv=disabled \
  -Djpeg=enabled \
  -Dv4l-plugins=true \
  -Dv4l-wrappers=true \
  `# ir-keytable installs its rc_keymaps into udevdir, which defaults to an` \
  `# absolute /lib/udev and fails with EACCES in a build sandbox. Keep it inside` \
  `# the prefix; the keymaps are only read by ir-keytable itself.` \
  -Dudevdir="${PREFIX}/lib/udev" \
  -Dsystemdsystemunitdir="${PREFIX}/lib/systemd/system" \
  --sysconfdir="${PREFIX}/etc"

meson compile -C builddir -j "${CPU_COUNT:-2}"
meson install -C builddir --no-rebuild

# The libv4l output owns these; keep them out of this package so the two do not
# clobber each other.
rm -f "${PREFIX}"/lib/libv4l*.so*
rm -rf "${PREFIX}"/lib/libv4l
rm -f "${PREFIX}"/include/libv4l*.h
rm -f "${PREFIX}"/lib/pkgconfig/libv4l*.pc
