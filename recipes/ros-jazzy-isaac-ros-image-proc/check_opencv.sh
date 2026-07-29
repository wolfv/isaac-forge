#!/usr/bin/env bash
# The reason this package is source-built: RectifyNode must link RoboStack's
# OpenCV, not Ubuntu noble's 4.6, and nothing may resolve outside the prefix.
#
# No pipefail: `producer | grep -q` exits non-zero *when it matches*, because
# grep -q closes the pipe and the producer dies of SIGPIPE.
set -u

SO="${PREFIX}/lib/librectify_node.so"
[ -f "${SO}" ] || { echo "FAIL: ${SO} missing"; exit 1; }

needed="$(patchelf --print-needed "${SO}" 2>/dev/null || readelf -d "${SO}")"

echo "== OpenCV linkage =="
case "${needed}" in
  *libopencv*406*) echo "FAIL: still linking Ubuntu's OpenCV 4.6 (.406)"; exit 1 ;;
esac
printf '%s\n' "${needed}" | grep -i opencv | sed 's/^/    /' || echo "    (none)"

echo "== resolving with only the prefix on the search path =="
gxf="$(find "${PREFIX}/share" -name '*.so' -path '*gxf*' -printf '%h\n' 2>/dev/null |
        sort -u | tr '\n' ':')"
out="$(LD_LIBRARY_PATH="${gxf}${PREFIX}/lib" ldd "${SO}" 2>&1)"

printf '%s\n' "${out}" | grep -E 'not found' | sed 's/^/    MISSING /' || true

leaked=0
while IFS= read -r line; do
  case "${line}" in *"=>"*) ;; *) continue ;; esac
  soname="$(echo "${line%%=>*}" | tr -d '[:space:]')"
  path="${line#*=> }"; path="$(echo "${path%% (*}" | tr -d '[:space:]')"
  case "${path}" in /*) ;; *) continue ;; esac
  case "${soname}" in
    libc.so*|libm.so*|libdl.so*|librt.so*|libpthread.so*|libgcc_s.so*|\
    libstdc++.so*|ld-linux-x86-64.so*|linux-vdso.so*) continue ;;
    # The CUDA driver always comes from the host driver package.
    libcuda.so*|libnvidia-*) continue ;;
  esac
  case "${path}" in
    "${PREFIX}"/*) ;;
    *) echo "    LEAKED ${soname} <- ${path}"; leaked=$((leaked + 1)) ;;
  esac
done <<EOF
${out}
EOF

if [ "${leaked}" -gt 0 ] || printf '%s\n' "${out}" | grep -q 'not found'; then
  echo "FAIL: unresolved or host-leaked dependencies"
  exit 1
fi

echo "PASS: RectifyNode links RoboStack OpenCV, all deps inside the prefix"
