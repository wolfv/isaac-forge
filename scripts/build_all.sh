#!/usr/bin/env bash
# Rebuild every recipe into ./output, which is the local channel everything resolves against.
#
# This existed only inside .github/workflows/release.yml, and that cost a day: when output/
# was lost between sessions there was no command in the repo that would rebuild it, and the
# `layer0` pixi task -- the obvious candidate -- passes no channels, so it cannot resolve
# ros-jazzy-isaac-ros-common and fails on the second recipe it reaches.
#
#     ./scripts/build_all.sh              # resume: skips what is already in output/
#     ./scripts/build_all.sh --fresh      # start over, discarding output/
#
# Three flags carry the design, and each was learned the hard way:
#
#   --test skip           Tests are skipped *during* the build and run afterwards by
#                         scripts/test_all.sh. A package's tests resolve its own run
#                         dependencies, and early in a from-scratch build those siblings do
#                         not exist yet -- so testing inline makes build order matter for
#                         reasons unrelated to compiling. Deferring removes the question.
#   --skip-existing local Makes the whole thing resumable. Nothing is rebuilt if its .conda
#                         is already in output/, so an interrupted run continues where it
#                         stopped and a second pass picks up newly added recipes.
#   --continue-on-failure One bad recipe does not stop the other 200. Without it a single
#                         failure ends the run, and with ~200 recipes that turns one problem
#                         into one problem per invocation.
#
# Build trees are pruned as packages land. rattler-build keeps output/bld/<pkg>_<stamp>/ for
# every build, and across the full set that is roughly 55 GB against ~6 GB of actual
# packages. Pruning as we go keeps the peak near the latter.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [ "${1:-}" = "--fresh" ]; then
  echo "removing output/ and starting over"
  rm -rf output
fi
mkdir -p output

CHANNELS=(-c ./output -c https://prefix.dev/robostack-jazzy -c conda-forge)

prune_finished() {
  local freed=0
  for d in output/bld/rattler-build_*; do
    [ -d "${d}" ] || continue
    # output/bld/rattler-build_<pkg-name>_<10-digit-stamp>
    local pkg
    pkg="$(basename "${d}" | sed 's/^rattler-build_//; s/_[0-9]\{10\}$//')"
    if ls output/linux-64/"${pkg}"-[0-9]*.conda >/dev/null 2>&1; then
      rm -rf "${d}" && freed=$((freed + 1))
    fi
  done
  [ "${freed}" -gt 0 ] && echo "  pruned ${freed} finished build trees"
  return 0
}

# Several passes, because a recipe added while an earlier pass was already running is not in
# that pass's plan. Each pass is cheap once the work is done -- --skip-existing local turns
# it into a directory listing -- and the loop stops as soon as a pass adds nothing.
total_before=0
for pass in 1 2 3 4; do
  before=$(ls output/linux-64/*.conda 2>/dev/null | wc -l)
  echo "=== pass ${pass} (${before} packages present) ==="
  rattler-build build \
    --recipe-dir recipes \
    --output-dir output \
    -m variants.yaml \
    --skip-existing local \
    --test skip \
    --continue-on-failure \
    "${CHANNELS[@]}" 2>&1 | tee "output/build-pass${pass}.log"
  prune_finished
  after=$(ls output/linux-64/*.conda 2>/dev/null | wc -l)
  echo "=== pass ${pass} finished: ${before} -> ${after} packages ==="
  if [ "${after}" = "${before}" ]; then
    echo "no progress in pass ${pass}; stopping"
    break
  fi
  total_before=${after}
done

echo
echo "built $(ls output/linux-64/*.conda 2>/dev/null | wc -l) of $(ls -d recipes/*/ | wc -l) recipes"
# One line per recipe that failed, so the summary is readable without opening the logs.
failed=$(cat output/build-pass*.log 2>/dev/null |
  awk '/Running build for recipe:/{r=$NF} /error   Work directory/{print r}' | sort -u)
if [ -n "${failed}" ]; then
  echo "failed:"
  printf '  %s\n' ${failed}
fi
echo "run ./scripts/test_all.sh next -- this script skipped every package test"
