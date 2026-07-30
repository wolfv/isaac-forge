#!/usr/bin/env bash
# Run every built package's own tests, against the finished channel.
#
# scripts/build_all.sh passes --test skip, so this is the other half of a rebuild and not an
# optional extra: the package_contents checks, the `find_package` configure checks and the
# import checks all live in the recipes and none of them has run until this does.
#
# Why afterwards rather than inline: a package's tests are resolved in a fresh environment
# built from its own run dependencies, and early in a from-scratch build those siblings do
# not exist in output/ yet. Testing inline therefore fails for reasons that have nothing to
# do with the package under test. By the time this runs, the whole set is present.
#
#     ./scripts/test_all.sh                 # every package in output/
#     ./scripts/test_all.sh nvblox visual   # only packages whose filename matches a pattern
#
# Every package is tested before anything is reported, so one broken package shows up as one
# failure rather than hiding the rest.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

CHANNELS=(-c ./output -c https://prefix.dev/robostack-jazzy -c conda-forge)

shopt -s nullglob
pkgs=(output/linux-64/*.conda output/noarch/*.conda)
present=${#pkgs[@]}

if [ "${present}" -eq 0 ]; then
  echo "no packages in output/ -- run ./scripts/build_all.sh first" >&2
  exit 1
fi

if [ "$#" -gt 0 ]; then
  filtered=()
  for p in "${pkgs[@]}"; do
    for pat in "$@"; do
      case "$(basename "${p}")" in *"${pat}"*) filtered+=("${p}"); break ;; esac
    done
  done
  pkgs=("${filtered[@]}")
  # Distinguished from an empty output/ on purpose: "no packages built" and "your filter
  # matched none of the packages that are built" want different next actions, and conflating
  # them sends you off to rebuild a channel that is already there.
  if [ "${#pkgs[@]}" -eq 0 ]; then
    echo "none of the ${present} package(s) in output/ match: $*" >&2
    exit 1
  fi
fi

echo "testing ${#pkgs[@]} package(s)"
mkdir -p output
: > output/test-failures.log
failed=()
for p in "${pkgs[@]}"; do
  name="$(basename "${p}")"
  printf '  %-72s ' "${name}"
  if rattler-build test --package-file "${p}" "${CHANNELS[@]}" \
       > "output/test-${name}.log" 2>&1; then
    echo "ok"
    rm -f "output/test-${name}.log"
  else
    echo "FAILED"
    failed+=("${name}")
    echo "${name}" >> output/test-failures.log
  fi
done

echo
if [ "${#failed[@]}" -gt 0 ]; then
  echo "${#failed[@]} of ${#pkgs[@]} package(s) failed their tests:"
  printf '  %s\n' "${failed[@]}"
  echo "per-package logs are in output/test-<package>.log"
  exit 1
fi
echo "all ${#pkgs[@]} packages passed their tests"
