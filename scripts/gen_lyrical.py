#!/usr/bin/env python3
"""Stage Isaac ROS 5 source recipes for Lyrical; never relabel Jazzy debs."""

from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parent.parent
out = root / "recipes-lyrical"
# RoboStack already builds these from the Lyrical rosdistro release.
robostack = {"rosidl-buffer", "rosidl-buffer-backend", "rosidl-buffer-backend-registry"}

wanted = set(sys.argv[1:])
out.mkdir(exist_ok=True)
for recipe in sorted((root / "recipes").glob("ros-jazzy-*/recipe.yaml")):
    text = recipe.read_text()
    if "built FROM SOURCE" not in text:
        raise ValueError(f"not a source recipe: {recipe}")
    name = recipe.parent.name.replace("ros-jazzy-", "ros-lyrical-", 1)
    if name.removeprefix("ros-lyrical-") in robostack or (wanted and name not in wanted):
        continue
    target = out / name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(recipe.parent, target)
    text = text.replace("ros-jazzy-", "ros-lyrical-")
    if name == "ros-lyrical-isaac-deploy-core":
        # package.xml switches from tl_expected to rcpputils on Lyrical.
        text = text.replace("    - ros-lyrical-tl-expected\n", "    - ros-lyrical-rcpputils\n")
    if "ros-jazzy-" in text or "/opt/ros/jazzy" in text:
        raise ValueError(f"Jazzy reference in {recipe}")
    (target / "recipe.yaml").write_text(text)
# VPI is an architecture-specific vendor library, not a ROS/Jazzy binary.
if not wanted or "vpi" in wanted:
    if (out / "vpi").exists():
        shutil.rmtree(out / "vpi")
    shutil.copytree(root / "recipes/vpi", out / "vpi")
print(f"staged {len(list(out.glob('*/recipe.yaml')))} Lyrical recipes in {out}")
