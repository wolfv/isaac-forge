#!/usr/bin/env python3
"""Build packages.json: an inventory of every Isaac ROS package in src/.

For each ROS package this records its repo, path, declared license and version,
its direct and conditional dependencies, its transitive closure over
Isaac-internal packages, and which known blockers that closure pulls in.

Run via `pixi run inventory` after cloning the sources with scripts/clone.sh.
"""

from __future__ import annotations

import collections
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")

# Dependency tags that affect what we must be able to resolve at build/run time.
# test_depend is deliberately excluded: a missing test dep does not block a build.
DEP_TAG = re.compile(
    r"<(build_depend|buildtool_depend|build_export_depend|exec_depend|depend"
    r"|buildtool_export_depend)([^>]*)>([^<]+)<"
)

# rosdep keys we still cannot obtain, grouped by what would unblock them.
#
# A key belongs here only while nothing can supply it. Once something can -- robostack,
# conda-forge, or a recipe in this repository -- it stops being a blocker and moves to
# RESOLVED below, because a package labelled blocked that in fact builds is worse than no
# label at all: it stops anyone from trying. Both entries in RESOLVED were labels of that
# kind for months.
BLOCKERS = {
    # Out of scope rather than missing: these are ROS 1, from isaac_ros_noetic_interfaces.
    "ros1": {"roscpp", "rospy", "catkin", "message_generation", "message_runtime", "nodelet"},
}

# Formerly in BLOCKERS, now supplied by this repository. Kept as data so the reason a
# package is *not* flagged stays visible, and so the next person can see what a resolved
# blocker looks like.
RESOLVED = {
    "vpi": {"libnvvpi4", "vpi4-dev"},            # recipes/vpi -- was under 219 packages
    "tensorrt": {"tensorrt"},                    # recipes/tensorrt -- was under 37
    # recipes/triton-server builds the public C API from source; isaac_ros_triton uses
    # its exported target instead of NVIDIA's unreachable private x86_64 tarball.
    "triton": {"triton-server"},                 # was under 27 packages
}

# GXF extensions NVIDIA ships only as prebuilt debs -- no source in any repo. This is a
# provenance fact, not a blocker: every one of them repacks cleanly from the apt index, and
# all nine that were outstanding are built. It stays in the output because "there is no
# source for this" is worth knowing; it no longer means "this cannot be had".
CLOSED_GXF = {
    "gxf_isaac_tensorops",
    "gxf_isaac_argus",
    "gxf_isaac_rectify",
    "gxf_isaac_sgm",
    "gxf_isaac_hesai",
}

# Dependencies that cannot be obtained at all -- neither from robostack-jazzy nor
# conda-forge, nor built in this repository.
#
# The distinction matters, and the list used to blur it: "not in robostack-jazzy" is not
# the same as "unavailable", and six entries were the former while being perfectly
# obtainable. Counting those as blockers overstated `needs_new_ros_pkg` by 85 packages --
# 129 flagged where 44 is the real number -- and that overstatement is the same
# measurement error that made the whole DNN stack look unreachable behind `tensorrt`.
#
# Removed as they became obtainable:
#   negotiated, topic_based_ros2_control  built here (no jazzy release exists; #15)
#   robotiq_controllers                   released into robostack-jazzy 2026-07-30
#   rosidl_generator_dds_idl              released into robostack-jazzy 2026-07-30
#   vision_msgs_rviz_plugins              released into robostack-jazzy 2026-07-30
#   unitree_api                            built here from unitreerobotics/unitree_ros2
#   cvcuda0-dev                           conda-forge libcvcuda-dev
#
# Note the two rviz/dds additions freed no packages on their own: everything naming them
# also names nova_carter_* or a lidar driver, which are still absent. They are off the list
# because they are obtainable, not because they unblocked anything.
MISSING_ROS = {
    # Hardware drivers with no jazzy release anywhere.
    "hesai_ros_driver",
    "sllidar_ros2",
    # NVIDIA's, and not published as source we can reach.
    "isaac-ros-cli",
    "isaac_ros_bi3d_interfaces",
    "isaac_ros_visual_mapping",
    "nova_carter_bringup",
    "nova_carter_description",
    "nova_developer_kit_description",
}

# Packages whose name is claimed by two different repos in src/. `info` below is keyed by
# package name, so the second one scanned wins -- and for nvblox_msgs the loser is the one
# that matters. isaac_ros_noetic_interfaces ships a catkin `nvblox_msgs` for ROS 1;
# isaac_ros_nvblox ships the jazzy one, whose only dependencies are isaac_ros_common and
# rosidl. Everything that depends on nvblox_msgs therefore shows up here with a `ros1`
# blocker it does not have: isaac_ros_cumotion and isaac_ros_cumotion_object_attachment are
# both built and both ROS 2 only.
#
# Skipping the ROS 1 copy is narrower than keying `info` on (repo, name), and leaves the
# rest of this script looking packages up by bare name, the way package.xml does.
NAME_COLLISIONS = {"nvblox_msgs"}
ROS1_REPO = "isaac_ros_noetic_interfaces"

OPEN_LICENSES = ("Apache", "MIT")


def tag(text: str, name: str, default: str = "?") -> str:
    m = re.search(rf"<{name}>([^<]+)</{name}>", text)
    return m.group(1).strip() if m else default


def scan() -> dict[str, dict]:
    if not os.path.isdir(SRC):
        sys.exit(f"no sources found at {SRC} -- run scripts/clone.sh first")

    info: dict[str, dict] = {}
    for path in glob.glob(os.path.join(SRC, "**", "package.xml"), recursive=True):
        text = open(path, encoding="utf-8", errors="replace").read()
        name = tag(text, "name", "")
        if not name:
            continue
        rel = os.path.relpath(path, SRC)
        repo = rel.split(os.sep)[0]

        # See NAME_COLLISIONS: the ROS 1 copy must not displace the jazzy one.
        if name in NAME_COLLISIONS and repo == ROS1_REPO:
            continue

        deps: set[str] = set()
        conditional: set[str] = set()
        for _kind, attrs, dep in DEP_TAG.findall(text):
            # condition="$ISAAC_ROS_PLATFORM == arm64-fastos" and friends are
            # platform-gated; counting them inflates the blocker numbers.
            (conditional if "condition" in attrs else deps).add(dep.strip())

        info[name] = {
            "repo": repo,
            "path": os.path.dirname(rel),
            "license": tag(text, "license"),
            "version": tag(text, "version"),
            "deps": sorted(deps),
            "conditional": sorted(conditional),
        }
    return info


def closure(info: dict[str, dict], name: str) -> set[str]:
    """Transitive closure over Isaac-internal dependencies only."""
    seen: set[str] = set()
    stack = [name]
    while stack:
        for dep in info[stack.pop()]["deps"]:
            if dep in info and dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return seen


def main() -> None:
    info = scan()
    rows = []
    for name, meta in sorted(info.items()):
        internal = closure(info, name)
        group = internal | {name}

        reachable: set[str] = set()
        for member in group:
            reachable |= set(info[member]["deps"])

        blockers = {key for key, keys in BLOCKERS.items() if reachable & keys}
        if reachable & CLOSED_GXF:
            blockers.add("closed_gxf")
        if reachable & MISSING_ROS:
            blockers.add("needs_new_ros_pkg")

        rows.append(
            {
                "name": name,
                "repo": meta["repo"],
                "path": meta["path"],
                "license": meta["license"],
                "version": meta["version"],
                "direct_deps": meta["deps"],
                "conditional_deps": meta["conditional"],
                "internal_closure": sorted(internal),
                "blockers": sorted(blockers),
                "proprietary": not meta["license"].startswith(OPEN_LICENSES),
                "closure_proprietary": any(
                    not info[m]["license"].startswith(OPEN_LICENSES) for m in group
                ),
            }
        )

    out = os.path.join(ROOT, "packages.json")
    with open(out, "w") as fh:
        json.dump(rows, fh, indent=1)

    print(f"{len(rows)} packages -> {os.path.relpath(out, ROOT)}\n")

    counts = collections.Counter(tuple(r["blockers"]) or ("<none>",) for r in rows)
    print("packages by blocker set:")
    for keys, n in counts.most_common():
        print(f"  {n:4d}  {', '.join(keys)}")

    print("\ntransitive reach of each blocker:")
    for key in ("vpi", "needs_new_ros_pkg", "tensorrt", "triton", "ros1", "closed_gxf"):
        print(f"  {key:20s} {sum(1 for r in rows if key in r['blockers']):4d}")

    print(f"\nproprietary packages: {sum(1 for r in rows if r['proprietary'])}")
    print(f"no blockers at all:   {sum(1 for r in rows if not r['blockers'])}")


if __name__ == "__main__":
    main()
