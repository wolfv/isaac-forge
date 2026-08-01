#!/usr/bin/env python3
"""Generate rattler-build repack recipes from the Isaac ROS apt index.

One recipe per deb. Each recipe downloads the official deb (pinned by sha256),
unpacks it into the conda prefix, and rewrites RUNPATHs to be $ORIGIN-relative so
no activation hook is needed -- unlike demo/, which uses LD_LIBRARY_PATH.

    python scripts/gen_repack.py demo/.cache/Packages ros-jazzy-isaac-ros-nitros
    python scripts/gen_repack.py --closure demo/.cache/Packages ros-jazzy-isaac-ros-visual-slam

With --closure, the full Isaac-side dependency closure of the named targets is
generated. --exclude skips a package explicitly; packages listed in SOURCE_BUILT and
EXTERNAL are skipped automatically, so regenerating cannot clobber a source recipe or
shadow a conda-forge package.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aptclosure import BASE, closure, deps_of, parse  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECIPES = os.path.join(ROOT, "recipes")

# Deb dependencies that a conda package must not carry:
#   - the libc/toolchain family, handled by the conda sysroot (see __glibc below)
#   - Tegra-only or irrelevant bits
DROP = {
    "libc6", "libgcc-s1", "libstdc++6", "libatomic1", "libm6", "libdl2",
    "nvsci",            # Tegra only; nothing dlopens it on x86_64
    "libgnat-23",       # Ada runtime, pulled in transitively and unused here
    "git", "iputils-ping", "mosquitto", "nodejs", "yarnpkg",
    "ros2-apt-source",
    # Host daemon used to configure datacenter GPUs. It is not a library dependency of
    # Triton and has no place inside a relocatable conda environment.
    "datacenter-gpu-manager-4-core",
}

# Deb name -> conda name. Anything not listed and not dropped is passed through,
# which is correct for ros-jazzy-* since RoboStack uses the same naming.
MAP = {
    "libnvvpi4": "vpi",
    "vpi4-dev": "vpi",
    # CV-CUDA comes from conda-forge, not a repack. Its libcvcuda 0.16 has a
    # cuda130 build, identical NVCV_* symbol version nodes to NVIDIA's 0.14, and
    # resolves every cvcuda/nvcv symbol the repacked Isaac binaries need.
    "libcvcuda0": "libcvcuda",
    "cvcuda0-dev": "libcvcuda-dev",
    "libnvcv-types0": "libcvcuda",
    "libucx0": "ucx",
    "libyaml-cpp0.8": "yaml-cpp",
    "libconsole-bridge1.0": "console_bridge",
    "libpython3.12t64": "python",
    "cuda-toolkit-13-0": "cuda-version",
    "libnvinfer10": "tensorrt",
    "libnvinfer-plugin10": "tensorrt",
    "libcudnn9-cuda-13": "cudnn",
    "libnccl2": "nccl",
    "libgflags2.2": "gflags",
    "libgoogle-glog0v6": "glog",
    "libboost-dev": "libboost-devel",
    # magic_enum is header-only, leaves nothing at runtime, and conda-forge has it.
    # Only the blob repacks declare it and none of our source builds call
    # find_package(magic_enum), so there is nothing to gain from a vendored copy.
    "ros-jazzy-magic-enum": "magic_enum",
    # conda-forge has no v4l package; see recipes/libv4l.
    "libv4l-0t64": "libv4l",
    "libv4lconvert0t64": "libv4l",
    "libv4l-dev": "libv4l",
}

# Ubuntu noble OpenCV 4.6 -> conda-forge's libopencv, pinned to 4.6 by the recipes that
# need the .406 soname.
#
# This used to point at an `opencv406-compat` package, on the assumption that conda-forge's
# newest OpenCV was the only one available and a soname shim would be required. It never
# got written, and it turns out not to be needed: conda-forge still carries libopencv
# 4.6.0, sonames and all, and `libopencv 4.6.*` resolves. The cost is real but bounded --
# 4.6.0 predates the jpeg -> libjpeg-turbo migration and drags qt-main 5.15 with it, so it
# cannot share an environment with `cv_bridge`, which is why
# ros-jazzy-isaac-ros-visual-mapping-tools is a separate output from the package a ROS
# consumer installs. See ISSUES.md #26.
MAP.update({
    f"libopencv-{mod}406t64": "libopencv"
    for mod in ("core", "imgproc", "calib3d", "stitching", "imgcodecs", "flann",
                "features2d", "videoio", "highgui", "video", "objdetect", "dnn",
                "photo", "ml", "shape", "superres", "videostab", "ts")
})
MAP["libopencv-dev"] = "libopencv"

# Ubuntu noble's other C++ libraries, all satisfied by conda-forge at the version Ubuntu
# ships. The t64 suffix is Debian's 64-bit-time_t transition, not a different library.
#
# libabsl is the exception and the reason recipes/libabseil-debian3-compat exists: Debian
# renames abseil's inline namespace to `debian3`, so conda-forge's identically-versioned
# libabseil defines different mangled names and cannot satisfy an Isaac binary. Everything
# else in this table is a plain version match, measured -- see ISSUES.md #26.
MAP.update({
    "libabsl20220623t64": "libabseil-debian3-compat",
    "libabsl-dev": "libabseil-debian3-compat",
    "libprotobuf32t64": "libprotobuf",       # protobuf 3.21, libprotobuf.so.32
    "libprotobuf-dev": "libprotobuf",
    "libprotoc-dev": "libprotobuf",
    "protobuf-compiler": "libprotobuf",
    "libgoogle-glog0v6t64": "glog",          # glog 0.6, libglog.so.1
    "libceres4t64": "ceres-solver",          # ceres 2.2, libceres.so.4
    "libceres-dev": "ceres-solver",
    "libeigen3-dev": "eigen",
    "nlohmann-json3-dev": "nlohmann_json",
    "libgomp1": "libgomp",
    "libnvonnxparsers10": "tensorrt",
    "libnvonnxparsers-dev": "tensorrt",
})

# Conda packages that satisfy a deb dependency but are NOT ours to build: they come
# from conda-forge, and generating a repack recipe for them would shadow a properly
# maintained package with a vendored copy. Kept out of recipe generation while still
# appearing in the dependency lists.
def is_source_recipe(name: str) -> bool:
    """True if recipes/<name> already holds a source-build recipe.

    Detected by inspecting the recipe rather than kept as a hand-maintained list: an
    explicit list silently went stale once already and gen_repack overwrote 27 source
    recipes with repacks. Anything fetching a tarball or a pinned commit is a source
    build and must not be clobbered.
    """
    p = os.path.join(RECIPES, name, "recipe.yaml")
    if not os.path.isfile(p):
        return False
    text = open(p, encoding="utf-8", errors="replace").read()
    return bool(re.search(r"archive/refs/tags|archive/[0-9a-f]{40}|linuxtv\.org", text))


EXTERNAL = {
    "libcvcuda", "libcvcuda-dev",   # conda-forge has 0.16 with a cuda130 build
    "libv4l",                       # see external/staged-recipes/v4l-utils
    "magic_enum",                   # header-only, already in conda-forge
    "ucx", "yaml-cpp", "console_bridge", "python", "cuda-version",
    "tensorrt", "cudnn", "gflags", "glog", "libboost-devel",
    "libabseil-debian3-compat",     # recipes/libabseil-debian3-compat, hand-written
    "nlohmann_json", "eigen", "ceres-solver", "libopencv",
}

# Repacks written by hand because the template below gets them materially wrong, and which
# regenerating would therefore make worse. is_source_recipe() cannot catch these -- they
# *are* repacks, so nothing in them looks like a source build.
#
# ros-jazzy-isaac-ros-visual-mapping is one deb producing two conda packages with
# incompatible run requirements, and it needs four fixups the template has no notion of:
# deduplicating headers and static libraries the deb ships twice, rewriting
# /usr/include/{eigen3,opencv4} out of two CMake export sets, and reaching a vendored
# cuVSLAM in a sibling directory. See its recipe.yaml and ISSUES.md #26.
HAND_WRITTEN = {
    "ros-jazzy-isaac-ros-visual-mapping",
    "vpi",
    "tensorrt",
}

# Sonames the linker cannot resolve at build time because they are dlopen'd, come
# from the driver, or live in a sibling package's share/ tree.
MISSING_DSO_OK = [
    "libcuda.so.*", "libnvidia-*.so.*",
    "libgxf_*.so", "libcuvslam.so", "libcumotion.so*",
    "libnvvpi.so.*", "libcvcuda.so.*", "libnvcv_types.so.*",
    "libopencv_*.so.406*",
]


def conda_name(deb: str) -> str | None:
    if deb in DROP:
        return None
    return MAP.get(deb, deb)


def clean_version(raw: str) -> str:
    """4.5.0-0noble.20260706155832051 -> 4.5.0 ; 0.1.0-0noble -> 0.1.0"""
    return re.split(r"[-+]", raw, maxsplit=1)[0]


def fetch_sha256(url: str, cache_dir: str) -> str:
    """Download once into cache_dir and hash it, so recipes are reproducible."""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, os.path.basename(url.split("?")[0]))
    if not os.path.exists(path):
        import urllib.request
        print(f"    fetching {os.path.basename(path)}", flush=True)
        urllib.request.urlretrieve(url, path)
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# Per-package fixups appended to build.sh, for upstream bugs we are licensed to fix
# in the files we ship. Keep these few, targeted and loud on failure, so a version
# bump that changes the layout is noticed rather than silently skipped.
POST_FIXUP = {
    # cuvslam2.h uses uint8_t but never includes <cstdint>; it only compiled for
    # NVIDIA because GCC 13 pulled it in transitively (ISSUES.md #1). Patching the
    # header we install fixes it for every consumer of this package, not just our
    # own builds -- unlike a -include cstdint in our CXXFLAGS.
    #
    # Licensing: cuvslam2.h carries the NVIDIA *Open* Software License, which grants
    # "commercially use, modify, and distribute". The Isaac ROS Software License that
    # covers the deb defers to per-component licenses in its section 7, so this file
    # is ours to fix.
    # nvv4l2 ships libcuvidv4l2_plugin.so, which is a libv4l2 *plugin* -- the deb
    # declares "Depends: libv4l-dev" with no Provides/Conflicts, so it extends libv4l
    # rather than replacing it. libv4l2 discovers plugins by globbing
    # <prefix>/lib/libv4l/plugins/*.so, but the deb installs the plugin flat into
    # the library directory, so nothing finds it and NVDEC silently stays
    # unavailable. Put it where libv4l2 looks.
    #
    # Note libnvv4l2.so declares SONAME libv4l2.so.0, the same as real libv4l2. The
    # loader resolves that name to libv4l's copy because that is the file actually
    # named libv4l2.so.0; NVIDIA's code is reached through the plugin, not the soname.
    "nvv4l2": r'''
PLUGIN_DIR="${PREFIX}/lib/libv4l/plugins"
mkdir -p "${PLUGIN_DIR}"
moved=0
for p in "${PREFIX}"/lib/*v4l2_plugin.so; do
  [ -f "${p}" ] || continue
  mv "${p}" "${PLUGIN_DIR}/"
  echo "moved $(basename "${p}") into lib/libv4l/plugins/"
  moved=$((moved + 1))
done
if [ "${moved}" -eq 0 ]; then
  echo "no *v4l2_plugin.so found -- layout changed, check POST_FIXUP" >&2
  exit 1
fi

# The deb payload lands both flat and under a multiarch subdir; drop the duplicate.
rm -rf "${PREFIX}/lib/x86_64-linux-gnu"
''',

    "ros-jazzy-isaac-ros-nitros": r'''
CUVSLAM_H="${PREFIX}/share/isaac_ros_nitros/cuvslam/include/cuvslam/cuvslam2.h"
if [ ! -f "${CUVSLAM_H}" ]; then
  echo "expected cuvslam2.h at ${CUVSLAM_H} -- layout changed, check POST_FIXUP" >&2
  exit 1
fi
if grep -q '#include <cstdint>' "${CUVSLAM_H}"; then
  echo "cuvslam2.h already includes <cstdint>; upstream fixed it, drop this fixup"
else
  sed -i '0,/#include <array>/s//#include <array>\n#include <cstdint>/' "${CUVSLAM_H}"
  grep -q '#include <cstdint>' "${CUVSLAM_H}" || {
    echo "failed to patch <cstdint> into cuvslam2.h" >&2; exit 1; }
  echo "patched missing #include <cstdint> into cuvslam2.h (ISSUES.md #1)"
fi
''',
}


BUILD_SH = r'''#!/usr/bin/env bash
set -euo pipefail

# Unpack the official Isaac ROS deb into the conda prefix.
#
# The debs use three layouts, all of which appear in the closure:
#   opt/ros/jazzy/{lib,share,include}      the ROS tree
#   opt/ros/jazzy/lib/x86_64-linux-gnu     Debian multiarch (e.g. negotiated)
#   opt/nvidia/<sdk>/lib                   NVIDIA SDK style (cvcuda, VPI)
STAGE="${SRC_DIR}/_stage"
mkdir -p "${STAGE}" "${PREFIX}/lib"
# One conda package can repack several debs -- e.g. libcvcuda comes from both
# libcvcuda0 (runtime .so) and cvcuda0-dev (the cvcuda/ and nvcv/ headers that
# isaac_ros_image_proc includes).
for deb in "${SRC_DIR}"/pkg*.deb; do
  bsdtar -xOf "${deb}" 'data.tar*' | bsdtar -xf - -C "${STAGE}"
done

# Flatten the Debian multiarch level into lib/ so the loader finds these without
# an extra search path -- but leave a symlink behind at the original location.
# The debs' generated CMake exports reference
# ${_IMPORT_PREFIX}/lib/x86_64-linux-gnu/<lib>, and those files have an EXISTS
# assertion that hard-fails configure if the path is gone (ros-jazzy-negotiated).
MULTIARCH="${STAGE}/opt/ros/jazzy/lib/x86_64-linux-gnu"
if [ -d "${MULTIARCH}" ]; then
  for f in "${MULTIARCH}"/*; do
    [ -e "${f}" ] || continue
    base="$(basename "${f}")"
    cp -a "${f}" "${STAGE}/opt/ros/jazzy/lib/${base}"
    rm -rf "${f}"
    ln -s "../${base}" "${MULTIARCH}/${base}"
  done
fi

# Note: written as if-blocks rather than `[ -d X ] && cp ...`, because under
# `set -e` that idiom aborts the script when the directory is simply absent --
# which is the normal case for the non-ROS SDK debs (libcvcuda, VPI).
if [ -d "${STAGE}/opt/ros/jazzy" ]; then
  cp -a "${STAGE}/opt/ros/jazzy/." "${PREFIX}/"
fi

for sdk in "${STAGE}"/opt/nvidia/*/; do
  [ -d "${sdk}" ] || continue
  for sub in lib lib/x86_64-linux-gnu lib64; do
    if [ -d "${sdk}${sub}" ] && [ ! -L "${sdk}${sub}" ]; then
      find "${sdk}${sub}" -maxdepth 1 \( -type f -o -type l \) -name '*.so*' \
        -exec cp -a {} "${PREFIX}/lib/" \;
    fi
  done
  if [ -d "${sdk}include" ]; then
    mkdir -p "${PREFIX}/include"
    cp -a "${sdk}include/." "${PREFIX}/include/"
  fi
done

for extra in usr/lib/x86_64-linux-gnu usr/lib; do
  if [ -d "${STAGE}/${extra}" ]; then
    mkdir -p "${PREFIX}/lib"
    cp -a "${STAGE}/${extra}/." "${PREFIX}/lib/"
  fi
done
if [ -d "${STAGE}/usr/include" ]; then
  mkdir -p "${PREFIX}/include"
  cp -a "${STAGE}/usr/include/." "${PREFIX}/include/"
fi

rm -rf "${STAGE}"

# Rewrite /opt/ros/jazzy to the build prefix in text files.
#
# The debs bake absolute paths into more than just RUNPATHs. The ament resource
# index is the one that bites first: share/ament_index/resource_index/
# isaac_ros_common_cmake_path/isaac_ros_common contains the literal string
# /opt/ros/jazzy/share/isaac_ros_common/cmake, and every Isaac CMakeLists does
#
#   ament_index_get_resource(ISAAC_ROS_COMMON_CMAKE_PATH isaac_ros_common_cmake_path isaac_ros_common)
#   include("${ISAAC_ROS_COMMON_CMAKE_PATH}/isaac_ros_common-version-info.cmake")
#
# which hard-fails when that path does not exist. The same applies to generated
# .cmake exports and the ament environment hooks.
#
# Writing ${PREFIX} literally is the right move in conda: rattler-build detects
# the build prefix in text files and rewrites it to the install prefix when the
# package is unpacked. grep -I skips binaries, which patchelf handles instead.
mapfile -t textfiles < <(grep -rIl '/opt/ros/jazzy' "${PREFIX}" 2>/dev/null || true)
if [ "${#textfiles[@]}" -gt 0 ]; then
  printf 'rewriting /opt/ros/jazzy -> $PREFIX in %d text files\n' "${#textfiles[@]}"
  for f in "${textfiles[@]}"; do
    sed -i "s|/opt/ros/jazzy|${PREFIX}|g" "${f}"
  done
fi

# Rewrite absolute RUNPATHs to $ORIGIN-relative ones.
#
# The debs bake in paths like /opt/ros/jazzy/share/isaac_ros_gxf/gxf/lib/std and
# /usr/local/cuda/lib64, which do not exist in a conda prefix. Since the tree
# layout under $PREFIX matches the layout under /opt/ros/jazzy, each entry maps
# cleanly onto $ORIGIN plus the right number of ".." hops for that file's depth.
python "${RECIPE_DIR}/relink.py" "${PREFIX}"
'''

RELINK_PY = r'''#!/usr/bin/env python3
"""Rewrite absolute RUNPATHs in a conda prefix to $ORIGIN-relative paths.

The Isaac ROS debs are built for /opt/ros/jazzy with hard-coded RUNPATHs. Their
directory layout is preserved verbatim under $PREFIX, so every absolute entry can
be re-expressed relative to the shared object's own location:

    /opt/ros/jazzy/lib                       -> $ORIGIN/<up>/lib
    /opt/ros/jazzy/share/<pkg>/gxf/lib/std   -> $ORIGIN/<up>/share/<pkg>/gxf/lib/std
    /usr/local/cuda/lib64                    -> $ORIGIN/<up>/lib   (conda flattens CUDA)
    /opt/nvidia/vpi4/lib/x86_64-linux-gnu    -> $ORIGIN/<up>/lib

where <up> is the number of ".." hops from the file's directory back to $PREFIX.
Doing this at build time means no LD_LIBRARY_PATH activation hook is needed.
"""

import os
import subprocess
import sys

PREFIX = os.path.realpath(sys.argv[1])

# Absolute prefixes that should collapse onto $PREFIX/lib.
TO_LIB = ("/usr/local/cuda/lib64", "/usr/local/cuda/targets/x86_64-linux/lib",
          "/usr/lib/x86_64-linux-gnu", "/usr/lib64", "/usr/lib", "/lib64")
ROS_ROOT = "/opt/ros/jazzy"


def is_elf(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == b"\x7fELF"
    except OSError:
        return False


def runpath(path: str) -> str:
    out = subprocess.run(["patchelf", "--print-rpath", path],
                         capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ""


def rewrite(entries: list[str], up: str) -> list[str]:
    origin = "$ORIGIN" if not up else f"$ORIGIN/{up}"
    out = []
    for e in entries:
        if not e:
            continue
        # GXF core is built with Bazel, so its RUNPATHs are littered with
        # $ORIGIN/../../_solib_k8/... and $ORIGIN/libfoo.so.runfiles/... entries
        # pointing into a Bazel output tree that does not ship. Drop them: they
        # are dead weight and make real problems hard to read.
        if "_solib_" in e or ".runfiles" in e:
            continue
        if e.startswith("$ORIGIN"):
            new = e
        elif e == ROS_ROOT or e.startswith(ROS_ROOT + "/"):
            rel = e[len(ROS_ROOT):].lstrip("/")
            new = f"{origin}/{rel}" if rel else origin
        elif any(e == p or e.startswith(p + "/") for p in TO_LIB):
            new = f"{origin}/lib"
        elif e.startswith("/opt/nvidia/"):
            new = f"{origin}/lib"
        else:
            # Unknown absolute path: drop it rather than leak a host directory
            # into the package.
            continue
        if new and new not in out:
            out.append(new)
    # Always be able to find siblings in $PREFIX/lib.
    for fallback in (origin, f"{origin}/lib"):
        if fallback not in out:
            out.append(fallback)
    return out


def link_gxf_into_lib() -> int:
    """Symlink GXF shared objects from share/**/gxf/lib** into $PREFIX/lib.

    GXF extensions must stay under share/<pkg>/gxf/lib because NITROS loads them
    by path from the ament resource index. But the dynamic linker also has to
    resolve them as NEEDED entries across package boundaries, and a package being
    built cannot know where a sibling package will put its libraries. Symlinking
    into the one directory every consumer already has on its RPATH ($PREFIX/lib)
    solves that without duplicating ~20 MB of binaries.
    """
    libdir = os.path.join(PREFIX, "lib")
    os.makedirs(libdir, exist_ok=True)
    linked = 0
    share = os.path.join(PREFIX, "share")
    for dirpath, _dirnames, filenames in os.walk(share):
        if f"{os.sep}gxf{os.sep}lib" not in dirpath:
            continue
        for name in filenames:
            if ".so" not in name:
                continue
            src = os.path.join(dirpath, name)
            if not is_elf(src):
                continue
            dst = os.path.join(libdir, name)
            if os.path.exists(dst) or os.path.islink(dst):
                continue
            os.symlink(os.path.relpath(src, libdir), dst)
            linked += 1
    if linked:
        print(f"symlinked {linked} GXF libraries into lib/")
    return linked


def main() -> None:
    changed = 0
    for dirpath, _dirnames, filenames in os.walk(PREFIX):
        for name in filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path) or not is_elf(path):
                continue
            old = runpath(path)
            rel = os.path.relpath(dirpath, PREFIX)
            depth = 0 if rel == "." else len(rel.split(os.sep))
            up = "/".join([".."] * depth)
            new = ":".join(rewrite(old.split(":") if old else [], up))
            if new != old:
                subprocess.run(["patchelf", "--set-rpath", new, path], check=True)
                changed += 1
                print(f"    {os.path.relpath(path, PREFIX)}")
                if old:
                    print(f"        was: {old}")
                print(f"        now: {new}")
    print(f"relinked {changed} binaries")

    link_gxf_into_lib()


if __name__ == "__main__":
    main()
'''


def shipped_sonames(entry: dict, cache: str, url: str) -> set[str]:
    """Library stems a non-ROS deb ships, for a package_contents `lib:` test.

    `lib: [cvcuda]` matches libcvcuda.so and libcvcuda.so.*, so the stem is what
    package_contents wants -- not the full filename.
    """
    import subprocess
    path = os.path.join(cache, os.path.basename(url.split("?")[0]))
    if not os.path.exists(path):
        return set()
    listing = subprocess.run(
        ["bash", "-c", f"bsdtar -xOf {path!r} 'data.tar*' | bsdtar -tf -"],
        capture_output=True, text=True,
    ).stdout
    stems = set()
    for line in listing.splitlines():
        base = os.path.basename(line.rstrip("/"))
        if ".so" not in base or not base.startswith("lib"):
            continue
        stem = base[3:].split(".so")[0]
        # Plugins are dlopen'd modules, not link targets, and POST_FIXUP relocates
        # them out of lib/ into the loader's plugin directory. A `lib:` soname test
        # is the wrong check for them; the fixup hard-fails if one goes missing.
        if stem.endswith("_plugin"):
            continue
        stems.add(stem)
    return stems


def emit(name: str, entries: list[dict], index: dict, cache: str) -> str:
    # Sort so the runtime deb comes first and the version is taken from it.
    entries = sorted(entries, key=lambda e: ("dev" in e["Package"], e["Package"]))
    version = clean_version(entries[0].get("Version", "0"))

    sources = []
    for i, e in enumerate(entries):
        url = f"{BASE}/{e['Filename']}"
        sources.append(
            f"  # {e['Package']}\n"
            f"  - url: {url}\n"
            f"    file_name: pkg{i}.deb\n"
            f"    sha256: {fetch_sha256(url, cache)}"
        )
    source_block = "\n".join(sources)

    run_deps: list[str] = []
    for e in entries:
        for dep in deps_of(e):
            mapped = conda_name(dep)
            if mapped and mapped != name and mapped not in run_deps:
                run_deps.append(mapped)

    dep_lines = "\n".join(f"    - {d}" for d in sorted(run_deps)) or "    # none"
    dso_lines = "\n".join(f"      - {p}" for p in MISSING_DSO_OK)

    # A ROS package always installs share/<pkg>/package.xml; a plain NVIDIA SDK
    # library (libcvcuda, ...) installs only shared objects.
    if name.startswith("ros-jazzy-"):
        ros_dir = name.replace("ros-jazzy-", "").replace("-", "_")
        content_test = (
            "      files:\n"
            "        # ROS dirs use underscores, conda package names use dashes.\n"
            f"        - share/{ros_dir}/package.xml"
        )
    else:
        content_test = "      lib:\n" + "\n".join(
            f"        - {so}"
            for so in sorted(
                set().union(*(shipped_sonames(e, cache, f"{BASE}/{e['Filename']}")
                              for e in entries))
            )
        )

    summary = entries[0].get("Description", name).splitlines()[0].strip()
    is_isaac_license = name.startswith(("ros-jazzy-isaac", "ros-jazzy-gxf-isaac"))
    lic = "LicenseRef-NVIDIA-Isaac-ROS" if is_isaac_license else "Apache-2.0"

    return f"""schema_version: 1

# Repacked from the official Isaac ROS debian package.
#
# Generated by scripts/gen_repack.py -- edit the generator, not this file.
#
# The binaries are NVIDIA's own, unmodified except for RUNPATH rewriting, which is
# required to make them relocatable inside a conda prefix (see relink.py).

context:
  version: "{version}"

package:
  name: {name}
  version: ${{{{ version }}}}

source:
{source_block}

build:
  # The apt index used to generate this recipe is amd64. Never publish its ELF
  # payload under an ARM subdir; ARM blob recipes must point at an ARM source.
  skip: target_platform == "linux-aarch64"
  number: 0
  script: build.sh
  dynamic_linking:
    # NVIDIA's binaries are relinked by relink.py, not by rattler-build.
    binary_relocation: false
    missing_dso_allowlist:
{dso_lines}

requirements:
  build:
    - libarchive          # bsdtar, reads .deb directly
    - patchelf
    - python
  run:
    # Built on Ubuntu 24.04, so the binaries reference GLIBC_2.38 symbols. This is
    # a hard requirement on the host glibc, hence a run dep rather than a
    # run_constraints entry.
    - __glibc >=2.38
{dep_lines}

tests:
  - package_contents:
{content_test}

about:
  homepage: https://github.com/NVIDIA-ISAAC-ROS
  summary: {summary}
  license: {lic}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("packages")
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--closure", action="store_true",
                    help="generate the whole Isaac-side dependency closure")
    ap.add_argument("--exclude", action="append", default=[],
                    help="skip this package (e.g. one built from source)")
    args = ap.parse_args()

    index = parse(args.packages)
    if args.closure:
        isaac, _external = closure(index, args.targets)
        names = sorted(isaac)
    else:
        names = args.targets

    cache = os.path.join(ROOT, "demo", ".cache", "debs")
    generated: set[str] = set()
    skipped: list[str] = []

    # Several debs can map onto one conda package (libcvcuda0 + cvcuda0-dev), so
    # group first and emit one recipe with one source entry per deb.
    groups: dict[str, list[dict]] = {}
    for deb in names:
        if deb in args.exclude:
            skipped.append(deb)
            continue
        entry = index.get(deb)
        if entry is None or "Filename" not in entry:
            skipped.append(deb)
            continue
        cname = conda_name(deb)
        if (cname is None or cname in EXTERNAL or cname in HAND_WRITTEN
                or is_source_recipe(cname)):
            skipped.append(deb)
            continue
        groups.setdefault(cname, []).append(entry)

    for cname, entries in sorted(groups.items()):
        d = os.path.join(RECIPES, cname)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "recipe.yaml"), "w") as fh:
            fh.write(emit(cname, entries, index, cache))
        with open(os.path.join(d, "build.sh"), "w") as fh:
            fh.write(BUILD_SH)
            fixup = POST_FIXUP.get(cname)
            if fixup:
                fh.write("\n# --- package-specific fixup (see POST_FIXUP in "
                         "scripts/gen_repack.py) ---\n")
                fh.write(fixup.lstrip("\n"))
        with open(os.path.join(d, "relink.py"), "w") as fh:
            fh.write(RELINK_PY)
        generated.add(cname)
        print(f"  + recipes/{cname}")

    print(f"\ngenerated {len(generated)} recipes")
    if skipped:
        print(f"skipped (excluded, dropped or not in the index): {', '.join(skipped)}")


if __name__ == "__main__":
    main()
