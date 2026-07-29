#!/usr/bin/env python3
"""Prove the manipulation packages are usable, not merely installed.

Three levels, cheapest first:

  1. every python module imports in a plain interpreter,
  2. the generated action types exist and are importable,
  3. every C++ composable node the packages register actually dlopens inside a
     component container.

(3) is the one that matters. The python packages are data plus imports and fail loudly;
the C++ ones link libcumotion.so, and a missing or mismatched symbol there does not show
up until something calls dlopen.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import time

MODULES = [
    "isaac_ros_manipulation_ros_python_utils",
    "isaac_ros_manipulation_orchestration",
    "isaac_ros_manipulation_pick_and_place",
    "isaac_ros_manipulation_pose_to_pose",
    "isaac_ros_manipulation_object_following",
    "isaac_ros_manipulation_robot_utils",
    "isaac_ros_manipulation_ur_driver_utils",
    "isaac_ros_manipulation_ur_isaac_sim_utils",
    "isaac_ros_manipulation_flexiv_driver_utils",
    "isaac_ros_manipulation_test_utils",
    "isaac_ros_launch_utils",
    "isaac_ros_test",
]

# The components that need no configuration to construct. CumotionPlanner is deliberately
# not here: it refuses to start without a URDF and XRDF, which is what manip/ik.sh gives
# it.
COMPONENTS = [
    ("isaac_ros_manipulation_servers", "nvidia::isaac::manipulation::ObjectInfoServer"),
    ("isaac_ros_manipulation_servers", "nvidia::isaac::manipulation::ObjectSelectionServer"),
    ("isaac_ros_cumotion_object_attachment",
     "nvidia::isaac_ros::cumotion::ObjectAttachmentNode"),
]

failures = 0


def report(ok: bool, what: str, detail: str = "") -> None:
    global failures
    if not ok:
        failures += 1
    print(f"  {'ok  ' if ok else 'FAIL'}  {what}{': ' + detail if detail else ''}")


print("python modules")
for mod in MODULES:
    try:
        importlib.import_module(mod)
        report(True, f"import {mod}")
    except Exception as exc:  # noqa: BLE001 -- any import failure is a packaging failure
        report(False, f"import {mod}", f"{type(exc).__name__}: {exc}")

print("\ngenerated interfaces")
try:
    from isaac_ros_cumotion_interfaces.action import MotionPlan  # noqa: F401
    from isaac_ros_manipulation_interfaces.action import PickAndPlace  # noqa: F401
    report(True, "action types PickAndPlace, MotionPlan")
except Exception as exc:  # noqa: BLE001
    report(False, "action types", f"{type(exc).__name__}: {exc}")

print("\nament index")
listed = subprocess.run(["ros2", "pkg", "list"], capture_output=True, text=True).stdout.split()
found = sorted(p for p in listed if "manipulation" in p or "cumotion" in p)
report(len(found) >= 21, f"ros2 pkg list sees {len(found)} manipulation/cumotion packages")
for pkg in found:
    print(f"          {pkg}")

print("\nC++ components (dlopen into a live container)")
container = subprocess.Popen(
    ["ros2", "run", "rclcpp_components", "component_container"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    for _ in range(40):
        if subprocess.run(["ros2", "component", "list"],
                          capture_output=True).returncode == 0:
            break
        time.sleep(0.5)
    for pkg, cls in COMPONENTS:
        out = subprocess.run(
            ["ros2", "component", "load", "/ComponentManager", pkg, cls],
            capture_output=True, text=True)
        loaded = "Loaded component" in out.stdout
        report(loaded, f"load {cls.split('::')[-1]}",
               "" if loaded else (out.stdout + out.stderr).strip().splitlines()[-1])
finally:
    container.terminate()
    container.wait(timeout=20)

print("\nFAILED" if failures else "\nall checks passed")
sys.exit(1 if failures else 0)
