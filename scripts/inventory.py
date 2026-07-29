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

# rosdep keys that have no conda equivalent yet, grouped by what unblocks them.
BLOCKERS = {
    "vpi": {"libnvvpi4", "vpi4-dev"},
    "tensorrt": {"tensorrt"},
    "triton": {"triton-server"},
    "ros1": {"roscpp", "rospy", "catkin", "message_generation", "message_runtime", "nodelet"},
}

# GXF extensions NVIDIA ships only as prebuilt debs -- no source in any repo.
CLOSED_GXF = {
    "gxf_isaac_tensorops",
    "gxf_isaac_argus",
    "gxf_isaac_rectify",
    "gxf_isaac_sgm",
    "gxf_isaac_hesai",
}

# Open-source ROS packages that robostack-jazzy does not carry yet.
MISSING_ROS = {
    "negotiated",
    "hesai_ros_driver",
    "topic_based_ros2_control",
    "isaac-ros-cli",
    "isaac_ros_bi3d_interfaces",
    "isaac_ros_visual_mapping",
    "nova_carter_bringup",
    "nova_carter_description",
    "nova_developer_kit_description",
    "robotiq_controllers",
    "rosidl_generator_dds_idl",
    "sllidar_ros2",
    "unitree_api",
    "vision_msgs_rviz_plugins",
    "cvcuda0-dev",
}

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

        deps: set[str] = set()
        conditional: set[str] = set()
        for _kind, attrs, dep in DEP_TAG.findall(text):
            # condition="$ISAAC_ROS_PLATFORM == arm64-fastos" and friends are
            # platform-gated; counting them inflates the blocker numbers.
            (conditional if "condition" in attrs else deps).add(dep.strip())

        info[name] = {
            "repo": rel.split(os.sep)[0],
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
    for key in ("vpi", "needs_new_ros_pkg", "tensorrt", "ros1", "triton", "closed_gxf"):
        print(f"  {key:20s} {sum(1 for r in rows if key in r['blockers']):4d}")

    print(f"\nproprietary packages: {sum(1 for r in rows if r['proprietary'])}")
    print(f"no blockers at all:   {sum(1 for r in rows if not r['blockers'])}")


if __name__ == "__main__":
    main()
