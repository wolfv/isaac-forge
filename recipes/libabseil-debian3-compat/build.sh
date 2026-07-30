#!/usr/bin/env bash
set -euo pipefail

# Unpack Ubuntu's libabsl20220623t64 and install only the versioned shared objects.
STAGE="${SRC_DIR}/_stage"
mkdir -p "${STAGE}" "${PREFIX}/lib"
bsdtar -xOf "${SRC_DIR}/libabsl.deb" 'data.tar*' | bsdtar -xf - -C "${STAGE}"

MULTIARCH="${STAGE}/usr/lib/x86_64-linux-gnu"
[ -d "${MULTIARCH}" ] || { echo "expected ${MULTIARCH} -- deb layout changed" >&2; exit 1; }

# Only libabsl_*.so.20220623*. No unversioned .so, no headers, no .a: this package is for
# loading, never for linking against. Anything that compiles should use conda-forge's
# libabseil, which is the same upstream release with upstream's namespace.
#
# The glob has to be `.so.20220623*`, not `.so.20220623`, and the reason cost a build:
# Debian ships the soname as a *symlink* onto libabsl_x.so.20220623.0.0. Copying only the
# name the loader asks for gives 64 dangling symlinks, and the first thing that notices is
# patchelf below -- "No such file or directory" on a file cp had just reported copying.
count=0
for so in "${MULTIARCH}"/libabsl_*.so.20220623*; do
  [ -e "${so}" ] || continue
  cp -a "${so}" "${PREFIX}/lib/"
  count=$((count + 1))
done
if [ "${count}" -eq 0 ]; then
  echo "no libabsl_*.so.20220623* found in the deb -- layout or soname changed" >&2
  exit 1
fi
echo "installed ${count} abseil files (soname symlinks + their targets)"

# Both halves of every pair must have arrived, or a soname resolves to nothing.
for link in "${PREFIX}"/lib/libabsl_*.so.20220623; do
  [ -e "${link}" ] || { echo "no soname symlinks installed" >&2; exit 1; }
  [ -e "$(readlink -f "${link}")" ] || {
    echo "dangling soname: $(basename "${link}")" >&2; exit 1; }
done

rm -rf "${STAGE}"

# Give each library $ORIGIN so its abseil siblings resolve.
#
# This is load-bearing and easy to get wrong. Debian's libraries carry no RUNPATH at all,
# because on Ubuntu they sit in a default loader directory. In a conda prefix they do not,
# and DT_RUNPATH -- unlike the obsolete DT_RPATH -- is *not* inherited down the dependency
# chain: the consumer's `$ORIGIN/../../lib` finds libabsl_status.so.20220623, and then the
# loader looks for libabsl_raw_logging_internal.so.20220623 using libabsl_status's own
# (empty) RUNPATH and the system paths, and fails. So each library needs its own.
patched=0
for so in "${PREFIX}"/lib/libabsl_*.so.20220623.*; do
  [ -f "${so}" ] && [ ! -L "${so}" ] || continue
  patchelf --set-rpath '$ORIGIN' "${so}"
  patched=$((patched + 1))
done
echo "set \$ORIGIN RUNPATH on ${patched} libraries"

# Every remaining DT_NEEDED must be either an abseil sibling or the C/C++ runtime. If a
# future Ubuntu build grows a dependency on something else, this stops the build rather
# than shipping a library that fails to load.
for so in "${PREFIX}"/lib/libabsl_*.so.20220623.*; do
  [ -f "${so}" ] && [ ! -L "${so}" ] || continue
  while read -r need; do
    case "${need}" in
      libabsl_*.so.20220623|ld-linux-x86-64.so.2|libc.so.6|libm.so.6|libgcc_s.so.1|libstdc++.so.6) ;;
      "") ;;
      *) echo "unexpected DT_NEEDED ${need} in $(basename "${so}")" >&2; exit 1 ;;
    esac
  done < <(patchelf --print-needed "${so}")
done
echo "DT_NEEDED closure is abseil + the C/C++ runtime only"
