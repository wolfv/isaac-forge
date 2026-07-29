#!/usr/bin/env bash
# The reason this package is built from source: every dependency of the node must
# resolve inside $PREFIX, with no fallback to a host library.
#
# The repacked deb wanted libboost_thread.so.1.83.0 and only appeared to work on
# hosts that happen to ship it (Fedora 43 does, in /lib64). Built from source
# against RoboStack's Boost, nothing should resolve outside the prefix.
#
# No pipefail: `producer | grep -q` exits non-zero *when it matches*, because
# grep -q closes the pipe and the producer dies of SIGPIPE.
set -u

SO="${PREFIX}/lib/libvisual_slam_node.so"
[ -f "${SO}" ] || { echo "FAIL: ${SO} missing"; exit 1; }

echo "== boost linkage =="
needed="$(patchelf --print-needed "${SO}" 2>/dev/null || readelf -d "${SO}")"
case "${needed}" in
  *libboost*1.83*) echo "FAIL: still linking Ubuntu's Boost 1.83"; exit 1 ;;
esac
printf '%s\n' "${needed}" | grep -i boost | sed 's/^/    /' || echo "    (none)"

echo "== resolving with only the prefix on the search path =="
gxf="$(find "${PREFIX}/share" -name '*.so' -path '*gxf*' -printf '%h\n' 2>/dev/null |
        sort -u | tr '\n' ':')"
cuvslam="${PREFIX}/share/isaac_ros_nitros/cuvslam/lib"

out="$(LD_LIBRARY_PATH="${gxf}${cuvslam}:${PREFIX}/lib" ldd "${SO}" 2>&1)"
printf '%s\n' "${out}" | grep -E 'not found' | sed 's/^/    MISSING /' || true

leaked=0
while IFS= read -r line; do
  case "${line}" in *"=>"*) ;; *) continue ;; esac
  soname="${line%%=>*}"; soname="$(echo "${soname}" | tr -d '[:space:]')"
  path="${line#*=> }"; path="${path%% (*}"; path="$(echo "${path}" | tr -d '[:space:]')"
  case "${path}" in /*) ;; *) continue ;; esac
  # ld.so and the libc/toolchain family always come from the host.
  case "${soname}" in
    libc.so*|libm.so*|libdl.so*|librt.so*|libpthread.so*|libgcc_s.so*|\
    libstdc++.so*|ld-linux-x86-64.so*|linux-vdso.so*) continue ;;
    # The CUDA driver is installed by the host driver package, never by conda.
    libcuda.so*|libnvidia-*) continue ;;
  esac
  case "${path}" in
    "${PREFIX}"/*) ;;
    *) echo "    LEAKED ${soname} <- ${path}"; leaked=$((leaked + 1)) ;;
  esac
done <<EOF
${out}
EOF

if [ "${leaked}" -gt 0 ]; then
  echo "FAIL: ${leaked} dependencies resolved outside the prefix"
  exit 1
fi

echo "PASS: all dependencies resolve inside the prefix, no host Boost"
