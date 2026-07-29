#!/usr/bin/env python3
"""Generate source-build rattler-build recipes for Isaac ROS packages.

Companion to gen_repack.py. Where that one unpacks NVIDIA's debs, this one compiles
published source against RoboStack, which is what we want wherever source exists.

Per-package build traits are detected from the actual CMakeLists.txt rather than
guessed: whether CUDA has to be enabled, whether it is a rosidl interface package,
whether it needs Eigen, and so on. Run it after ./scripts/fetch_sources.sh has
populated the source cache.

    python scripts/gen_source.py                 # all packages in PACKAGES
    python scripts/gen_source.py <name> [...]    # just these
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_repack import DROP, EXTERNAL, MAP  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECIPES = os.path.join(ROOT, "recipes")
CACHE = os.path.join(ROOT, ".srccache")

# Upstream tarballs. Everything NVIDIA is pinned to the v4.5-0 release tag; osrf's
# negotiated has no tags at all, so it is pinned to a commit.
REPOS = {
    "isaac_ros_nitros": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_nitros/archive/refs/tags/v4.5-0.tar.gz",
        sha256="a8814fd02843a1098d00173671f03115b3b3575aabb078be371a7f977ad1e5c2"),
    "isaac_ros_common": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_common/archive/refs/tags/v4.5-0.tar.gz",
        sha256="b7a2bb09bad33c3654750a412c2c902064e8256088e1b1391ecd1dbcd803d0f7"),
    "isaac_ros_image_pipeline": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_image_pipeline/archive/refs/tags/v4.5-0.tar.gz",
        sha256="66a0ea87a075c4eb428faa4b987768928ae0250e6ab801db4bcbeef8fa8924b1"),
    "isaac_ros_visual_slam": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/archive/refs/tags/v4.5-0.tar.gz",
        sha256="8708fb6b016138483d24e785fa8549243839fe312d63786df2bba8840b5703f9"),
    "isaac_ros_benchmark": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_benchmark/archive/refs/tags/v4.5-0.tar.gz",
        sha256="3f37f7d22571a43f58b9a701940e8ee12c001f753fd5637be1e6d78a4bee1721"),
    "ros2_benchmark": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/ros2_benchmark/archive/refs/tags/v4.5-0.tar.gz",
        sha256="9077a56c57337a7d34a5da1068d06e9b2ed550180e8566012e93f6f6dd1d4d63"),
    "negotiated": dict(
        url="https://github.com/osrf/negotiated/archive/"
            "eac198b55dcd052af5988f0f174902913c5f20e7.tar.gz",
        sha256="01aed43adef3e6ef3d9e1879d3a2910d6acdcf802e6ea2905ab4626e21d7af05"),
}

# conda package name -> (repo, path within the repo). Order here is the build order:
# interfaces and leaf libraries first, so a plain sequential build resolves.
PACKAGES = [
    # rosidl interface packages -- no Isaac deps, safe to go first
    ("ros-jazzy-isaac-ros-tensor-list-interfaces", "isaac_ros_common", "isaac_ros_tensor_list_interfaces"),
    ("ros-jazzy-isaac-ros-pointcloud-interfaces", "isaac_ros_common", "isaac_ros_pointcloud_interfaces"),
    ("ros-jazzy-isaac-ros-visual-slam-interfaces", "isaac_ros_visual_slam", "isaac_ros_visual_slam_interfaces"),
    ("ros-jazzy-ros2-benchmark-interfaces", "ros2_benchmark", "ros2_benchmark_interfaces"),
    ("ros-jazzy-negotiated-interfaces", "negotiated", "negotiated_interfaces"),
    ("ros-jazzy-negotiated", "negotiated", "negotiated"),
    # small libraries
    ("ros-jazzy-isaac-common", "isaac_ros_common", "isaac_common"),
    ("ros-jazzy-gxf-isaac-gems", "isaac_ros_nitros", "isaac_ros_gxf_extensions/gxf_isaac_gems"),
    # NITROS type adapters -- thin wrappers over the core
    ("ros-jazzy-isaac-ros-nitros-std-msg-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_std_msg_type"),
    ("ros-jazzy-isaac-ros-nitros-image-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_image_type"),
    ("ros-jazzy-isaac-ros-nitros-camera-info-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_camera_info_type"),
    ("ros-jazzy-isaac-ros-nitros-tensor-list-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_tensor_list_type"),
    ("ros-jazzy-isaac-ros-nitros-compressed-image-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_compressed_image_type"),
    ("ros-jazzy-isaac-ros-nitros-disparity-image-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_disparity_image_type"),
    ("ros-jazzy-isaac-ros-nitros-point-cloud-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_point_cloud_type"),
    ("ros-jazzy-isaac-ros-nitros-detection2-d-array-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_detection2_d_array_type"),
    ("ros-jazzy-isaac-ros-nitros-detection3-d-array-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_detection3_d_array_type"),
    ("ros-jazzy-isaac-ros-nitros-flat-scan-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_flat_scan_type"),
    ("ros-jazzy-isaac-ros-nitros-imu-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_imu_type"),
    ("ros-jazzy-isaac-ros-nitros-occupancy-grid-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_occupancy_grid_type"),
    ("ros-jazzy-isaac-ros-nitros-pose-cov-stamped-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_pose_cov_stamped_type"),
    ("ros-jazzy-isaac-ros-managed-nitros", "isaac_ros_nitros", "isaac_ros_managed_nitros"),
    # utility libraries over NITROS
    ("ros-jazzy-isaac-ros-vpi-utils", "isaac_ros_image_pipeline", "isaac_ros_vpi_utils"),
    ("ros-jazzy-isaac-ros-cvcuda-utils", "isaac_ros_image_pipeline", "isaac_ros_cvcuda_utils"),
    # benchmark harness
    ("ros-jazzy-ros2-benchmark", "ros2_benchmark", "ros2_benchmark"),
    ("ros-jazzy-isaac-ros-benchmark", "isaac_ros_benchmark", "isaac_ros_benchmark"),
    ("ros-jazzy-isaac-ros-image-proc-benchmark", "isaac_ros_benchmark", "benchmarks/isaac_ros_image_proc_benchmark"),
]

DEP_TAG = re.compile(
    r"<(build_depend|buildtool_depend|build_export_depend|exec_depend|depend"
    r"|buildtool_export_depend|test_depend)([^>]*)>([^<]+)<")

# Dependencies that only matter for linting or tests.
TEST_ONLY = {
    "ament_lint_auto", "ament_lint_common", "ament_cmake_gtest", "ament_cmake_pytest",
    "ament_flake8", "ament_pep257", "ament_copyright", "ament_cmake_copyright",
    "ament_cmake_lint_cmake", "launch_testing", "launch_testing_ament_cmake",
    "launch_testing_ros", "python3-pytest", "isaac_ros_test", "isaac_ros_test_cmake",
    "python3-flaky",
}

# Extra host requirements keyed on what the CMakeLists actually does.
TRAIT_DEPS = {
    # The CUDA *compiler* is not listed here -- it belongs in build:, and is added as
    # ${{ compiler('cuda') }} below. Only the libraries and headers go in host.
    "cuda":   ["cuda-version 13.*", "cuda-cudart-dev", "cuda-nvtx-dev"],
    "eigen":  ["eigen 3.4.*"],
    "vpi":    ["vpi"],
    "yamlcpp": ["yaml-cpp"],
    "rosidl": ["ros-jazzy-rosidl-default-generators", "ros-jazzy-rosidl-default-runtime"],
    "python": ["python", "pyyaml"],
    "ament_auto": ["ros-jazzy-ament-cmake-auto"],
    "opencv": ["libopencv 4.13.*"],
    "cvcuda": ["libcvcuda", "libcvcuda-dev"],
}


# Patches applied to a package's source, all of them prepared for upstream. Keyed by
# conda package name; paths are relative to the recipe directory.
PATCHES = {
    # Explicit specializations of a variable template are not implicitly inline, so
    # epsilon.hpp produces multiple definitions of MachineEpsilon<float|double> in any
    # target with two TUs including it. Breaks
    # isaac_ros_nitros_detection3_d_array_type at link time under GCC 15.
    # Apache-2.0, so ours to fix; see ISSUES.md and upstream/README.md.
    "ros-jazzy-gxf-isaac-gems": ["patches/0001-epsilon-odr-inline.patch"],
}


def src_dir(repo: str) -> str:
    return os.path.join(CACHE, repo)


def detect(cml: str, pkgxml: str, path: str) -> set[str]:
    """Work out build traits from the package's own CMakeLists and manifest."""
    traits = set()
    if re.search(r"LANGUAGES[^)]*\bCUDA\b|enable_language\(\s*CUDA", cml):
        traits.add("cuda")
    if "find_package(CUDAToolkit" in cml:
        traits.add("cuda")
    if re.search(r"find_package\(\s*Eigen3", cml):
        traits.add("eigen")
    if re.search(r"find_package\(\s*vpi", cml):
        traits.add("vpi")
    if re.search(r"find_package\(\s*yaml-cpp", cml):
        traits.add("yamlcpp")
    if "rosidl_generate_interfaces" in cml:
        traits.add("rosidl")
    # isaac_ros_common's version-info helper shells out to python and imports yaml.
    if "isaac_ros_common-version-info" in cml or "generate_version_info" in cml:
        traits.add("python")
    # Trust CMakeLists over package.xml for build tooling. Several packages declare
    # only ament_cmake in the manifest but call find_package(ament_cmake_auto), so
    # deriving this from the manifest alone fails to configure.
    if "find_package(ament_cmake_auto" in cml:
        traits.add("ament_auto")
    if re.search(r"find_package\(\s*OpenCV", cml):
        traits.add("opencv")
    if re.search(r"find_package\(\s*cvcuda|nvcv", cml):
        traits.add("cvcuda")
    return traits


# package.xml uses bare rosdep keys, not deb names, so a second mapping layer is
# needed on top of gen_repack's MAP. Anything not listed here and not obviously a
# system package is assumed to be a ROS package and gets the ros-jazzy- prefix.
SYSTEM = {
    "cuda-toolkit": "cuda-version 13.*",
    "eigen": "eigen 3.4.*",
    "eigen3": "eigen 3.4.*",
    "yaml-cpp": "yaml-cpp",
    "boost": "libboost-devel",
    "libopencv-dev": "libopencv 4.13.*",
    "magic_enum": "magic_enum",
    "nlohmann_json": "nlohmann_json",
    "python3-numpy": "numpy",
    "python3-pytest": None,
    "python3-opencv": "py-opencv",
    "python3-matplotlib": "matplotlib-base",
    "python3-scipy": "scipy",
    "libgflags-dev": "gflags",
    "libgoogle-glog-dev": "glog",
    "assimp": "assimp",
    "tl_expected": "tl-expected",
    "benchmark": "benchmark",
    "posix_ipc": "posix_ipc",
    "git": None,
    "iputils-ping": None,
}


def ros_name(dep: str) -> str:
    return "ros-jazzy-" + dep.replace("_", "-")


def deps_of(pkgxml: str, name: str) -> list[str]:
    out: list[str] = []
    for kind, attrs, dep in DEP_TAG.findall(pkgxml):
        dep = dep.strip()
        if kind == "test_depend" or dep in TEST_ONLY or "condition" in attrs:
            continue
        if dep in DROP:
            continue
        if dep in SYSTEM:
            mapped = SYSTEM[dep]
            if mapped is None:
                continue
        elif dep in MAP:
            mapped = MAP[dep]
        elif dep.startswith(("python3-", "lib")) or "-" in dep:
            # An unrecognised system-looking key: skip rather than invent a ROS
            # package that does not exist, and let the build tell us if it mattered.
            print(f"     note {name}: skipping unmapped system dep '{dep}'")
            continue
        else:
            mapped = ros_name(dep)
        if mapped == name or mapped in out:
            continue
        out.append(mapped)
    return sorted(out)


def emit(name: str, repo: str, path: str) -> str | None:
    base = os.path.join(src_dir(repo), path)
    cml_p, pkg_p = os.path.join(base, "CMakeLists.txt"), os.path.join(base, "package.xml")
    if not os.path.isfile(pkg_p):
        print(f"  !! {name}: no package.xml at {path}")
        return None
    cml = open(cml_p, encoding="utf-8", errors="replace").read() if os.path.isfile(cml_p) else ""
    pkgxml = open(pkg_p, encoding="utf-8", errors="replace").read()

    version = (re.search(r"<version>([^<]+)</version>", pkgxml) or [None, "0"])[1].strip()
    lic_raw = (re.search(r"<license>([^<]+)</license>", pkgxml) or [None, "?"])[1].strip()
    lic = "Apache-2.0" if lic_raw.startswith("Apache") else "LicenseRef-NVIDIA-Isaac-ROS"
    summary = re.sub(r"\s+", " ",
                     (re.search(r"<description>([\s\S]*?)</description>", pkgxml)
                      or [None, name])[1]).strip().strip('"')[:110] or name

    traits = detect(cml, pkgxml, path)
    deps = deps_of(pkgxml, name)

    host = list(deps)
    for t in sorted(traits):
        for extra in TRAIT_DEPS[t]:
            if extra.endswith("# [build]"):
                continue
            if extra not in host:
                host.append(extra)

    build_tools = ["${{ compiler('c') }}", "${{ compiler('cxx') }}", "cmake", "ninja",
                   "pkg-config"]
    if "cuda" in traits:
        # Most of these packages have no .cu sources, so nothing is compiled by nvcc.
        # The compiler is here for its activation script: it puts
        # $PREFIX/targets/<arch>/include on CXXFLAGS and exports the CMAKE_ARGS the
        # build script passes to cmake. Without it, find_package(CUDAToolkit) falls back
        # to /usr/local/cuda and silently compiles against the build machine's CUDA --
        # see README.md. Never a host dep. Requires cuda_compiler_version from
        # ../variants.yaml, or the build fails to resolve.
        build_tools.insert(2, "${{ compiler('cuda') }}")

    # Runtime deps: drop build-only tooling.
    run = [d for d in deps if not d.startswith(("ros-jazzy-ament-cmake", "ament_cmake"))
           and d not in ("ros-jazzy-rosidl-default-generators",)]
    if "rosidl" in traits and "ros-jazzy-rosidl-default-runtime" not in run:
        run.append("ros-jazzy-rosidl-default-runtime")
    if "vpi" in traits and "vpi" not in run:
        run.append("vpi")

    ros_dir = name.replace("ros-jazzy-", "").replace("-", "_")
    repo_info = REPOS[repo]

    def block(items, indent=4):
        return "\n".join(f"{' ' * indent}- {i}" for i in items) or f"{' ' * indent}# none"

    trait_note = (f"\n# Detected build traits: {', '.join(sorted(traits))}."
                  if traits else "\n# No special build traits detected.")

    pats = PATCHES.get(name, [])
    patch_block = ("    patches:\n" + "\n".join(f"      - {x}" for x in pats)
                   if pats else "")

    return f"""schema_version: 1

# {name}, built FROM SOURCE against RoboStack.
#
# Generated by scripts/gen_source.py -- edit the generator, not this file.
# Source: {repo}/{path}{trait_note}

context:
  version: "{version}"

package:
  name: {name}
  version: ${{{{ version }}}}

source:
  - url: {repo_info['url']}
    sha256: {repo_info['sha256']}
    target_directory: src
{patch_block}
build:
  number: 0
  script:
    - export AMENT_PREFIX_PATH="${{PREFIX}}${{AMENT_PREFIX_PATH:+:${{AMENT_PREFIX_PATH}}}}"
    - export CMAKE_PREFIX_PATH="${{PREFIX}}${{CMAKE_PREFIX_PATH:+:${{CMAKE_PREFIX_PATH}}}}"
    - cd src/{path}
    # ${{CMAKE_ARGS}} carries the compiler activation's CMAKE_FIND_ROOT_PATH, which is
    # what points find_package(CUDAToolkit) at the prefix rather than /usr/local/cuda.
    - >
      cmake -S . -B build -G Ninja ${{CMAKE_ARGS:-}}
      -DCMAKE_BUILD_TYPE=Release
      -DCMAKE_INSTALL_PREFIX="${{PREFIX}}"
      -DCMAKE_PREFIX_PATH="${{PREFIX}}"
      -DCMAKE_CUDA_ARCHITECTURES="80;86;89;90"
      -DPYTHON_EXECUTABLE="${{PREFIX}}/bin/python"
      -DBUILD_TESTING=OFF
    - cmake --build build --parallel "${{CPU_COUNT:-2}}"
    - cmake --install build
  dynamic_linking:
    missing_dso_allowlist:
      # GXF extensions live in sibling packages' share/ trees; cuVSLAM and the VPI
      # backends are dlopen'd or resolved through the ament index.
      - libgxf_*.so
      - libcuvslam.so
      - libcumotion.so*
      - libnvvpi.so.*

requirements:
  build:
{block(build_tools)}
  host:
{block(host)}
  run:
    - __glibc >=2.38
{block(run)}

tests:
  - package_contents:
      files:
        - share/{ros_dir}/package.xml

about:
  homepage: https://github.com/NVIDIA-ISAAC-ROS/{repo}
  summary: {summary}
  license: {lic}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    args = ap.parse_args()

    wanted = set(args.names) if args.names else None
    written = 0
    for name, repo, path in PACKAGES:
        if wanted and name not in wanted:
            continue
        if name in EXTERNAL:
            continue
        text = emit(name, repo, path)
        if text is None:
            continue
        d = os.path.join(RECIPES, name)
        os.makedirs(d, exist_ok=True)
        # Replace any repack recipe wholesale.
        for stale in ("build.sh", "relink.py"):
            p = os.path.join(d, stale)
            if os.path.exists(p):
                os.remove(p)
        with open(os.path.join(d, "recipe.yaml"), "w") as fh:
            fh.write(text)
        print(f"  + recipes/{name}")
        written += 1
    print(f"\ngenerated {written} source recipes")


if __name__ == "__main__":
    main()
