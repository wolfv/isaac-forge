#!/usr/bin/env bash
# The specific failure this recipe guards against: a GitHub tarball carries git-lfs
# pointers, so a naive source build installs 132 bytes of text where libcuvslam.so
# belongs and cuVSLAM breaks only at runtime.
set -u

fail=0
check_elf() {
  local f="$1"
  if [ ! -f "${f}" ]; then echo "    MISSING ${f#"${PREFIX}"/}"; fail=1; return; fi
  if head -c 40 "${f}" | grep -q 'git-lfs.github.com'; then
    echo "    LFS POINTER ${f#"${PREFIX}"/} ($(stat -c%s "${f}") bytes)"; fail=1; return
  fi
  # Accept both ELF shared objects and ar static archives (libcuapriltags.a).
  magic="$(head -c 8 "${f}")"
  case "${magic}" in
    *ELF*|'!<arch>'*) ;;
    *) echo "    NOT A BINARY ${f#"${PREFIX}"/}"; fail=1; return ;;
  esac
  echo "    ok $(basename "${f}")  $(stat -c%s "${f}") bytes"
}

echo "== vendored SDK binaries =="
check_elf "${PREFIX}/share/isaac_ros_nitros/cuvslam/lib/libcuvslam.so"
check_elf "${PREFIX}/share/isaac_ros_nitros/cuapriltags/lib/libcuapriltags.a"

echo "== ament resources resolve to real directories =="
for res in cuvslam cuapriltags cumotion; do
  p="${PREFIX}/share/ament_index/resource_index/${res}/isaac_ros_nitros"
  if [ ! -f "${p}" ]; then echo "    MISSING resource ${res}"; fail=1; continue; fi
  rel="$(cat "${p}")"
  if [ -d "${PREFIX}/${rel}" ]; then echo "    ok ${res} -> ${rel}"
  else echo "    BROKEN ${res} -> ${rel}"; fail=1; fi
done

echo "== the library itself was compiled here, not copied =="
check_elf "${PREFIX}/lib/libisaac_ros_nitros.so"

[ "${fail}" -eq 0 ] || { echo "FAIL"; exit 1; }
echo "PASS: library built from source, vendored blobs are real binaries"
