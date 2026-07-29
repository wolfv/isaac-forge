#!/usr/bin/env bash
# The reason this package is source-built rather than repacked: DT_NEEDED must
# contain no absolute paths. The repacked binary had three, and the only way to fix
# them there was to rewrite strings inside NVIDIA's .so.
#
# No pipefail: `producer | grep -q` exits non-zero when it matches, because grep -q
# closes the pipe and the producer dies of SIGPIPE.
set -u

SO="${PREFIX}/lib/libdecoder_node.so"
[ -f "${SO}" ] || { echo "FAIL: ${SO} missing"; exit 1; }

echo "== DT_NEEDED =="
needed="$(patchelf --print-needed "${SO}" 2>/dev/null || readelf -d "${SO}")"
printf '%s\n' "${needed}" | grep -E 'nvbuf|nvv4l2|cuvid|v4l2' | sed 's/^/    /' || true

abs="$(printf '%s\n' "${needed}" | grep -c '^/' || true)"
if [ "${abs}" -ne 0 ]; then
  echo "FAIL: ${abs} absolute path(s) in DT_NEEDED:"
  printf '%s\n' "${needed}" | grep '^/' | sed 's/^/    /'
  exit 1
fi

echo "PASS: no absolute paths in DT_NEEDED -- relocatable without binary editing"

# A CUDA 12 header reaching this build is silent at build time and only shows up as an
# undefined symbol when the node is dlopened, so assert it here instead. CUDA 12's
# cuda_runtime_api.h aliases cudaGetDeviceProperties to the _v2 name; CUDA 13 dropped
# the alias and libcudart.so.13 exports only the unversioned name.
echo "== CUDA symbol versions =="
v2="$(nm -D --undefined-only "${SO}" 2>/dev/null | grep -c 'cuda[A-Za-z]*_v2' || true)"
if [ "${v2}" -ne 0 ]; then
  echo "FAIL: ${v2} CUDA 12-era _v2 symbol(s) referenced -- a host CUDA 12 header"
  echo "      reached the build. Check that the CUDA compiler is in build: and that"
  echo "      build.sh passes \${CMAKE_ARGS}, so FindCUDAToolkit resolves against the"
  echo "      prefix rather than /usr/local/cuda:"
  nm -D --undefined-only "${SO}" | grep 'cuda[A-Za-z]*_v2' | sed 's/^/    /'
  exit 1
fi

echo "PASS: no CUDA 12 _v2 symbol references -- built against the CUDA 13 headers"
