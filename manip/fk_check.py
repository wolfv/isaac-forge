#!/usr/bin/env python3
"""Check a cuMotion IK solution by computing forward kinematics independently.

cuMotion returning "26 solutions, SUCCEEDED" proves the library runs. It does not prove
the numbers are right, and the two are not the same claim -- especially when the answer
changes after rebuilding against a different Eigen (see ISSUES.md #13). So: parse the URDF
here, compose the joint transforms with numpy, and see whether the joint angles cuMotion
returned actually put the gripper where the goal asked.

No ROS, no kdl, no MoveIt -- a deliberately independent implementation, so agreement means
something.

    python fk_check.py J1 J2 J3 J4 J5 J6         # the six arm joints, radians
    python fk_check.py --goal X Y Z -- J1 ... J6  # with an explicit goal position
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET

import numpy as np

ARM_JOINTS = [
    "shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint",
    "wrist_1_joint", "wrist_2_joint", "wrist_3_joint",
]
TARGET_LINK = "gripper_frame"   # the XRDF's tool_frames entry, i.e. what IK solves for


def rpy(r: float, p: float, y: float) -> np.ndarray:
    cr, sr, cp, sp, cy, sy = np.cos(r), np.sin(r), np.cos(p), np.sin(p), np.cos(y), np.sin(y)
    return np.array([
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp,     cp * sr,                cp * cr],
    ])


def axis_angle(axis: np.ndarray, q: float) -> np.ndarray:
    axis = axis / np.linalg.norm(axis)
    x, y, z = axis
    c, s, C = np.cos(q), np.sin(q), 1.0 - np.cos(q)
    return np.array([
        [x * x * C + c,     x * y * C - z * s, x * z * C + y * s],
        [y * x * C + z * s, y * y * C + c,     y * z * C - x * s],
        [z * x * C - y * s, z * y * C + x * s, z * z * C + c],
    ])


def homogeneous(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = R, t
    return T


def load_joints(urdf_path: str) -> dict[str, dict]:
    root = ET.parse(urdf_path).getroot()
    joints = {}
    for j in root.findall("joint"):
        origin = j.find("origin")
        xyz = [float(v) for v in (origin.get("xyz", "0 0 0") if origin is not None
                                  else "0 0 0").split()]
        rot = [float(v) for v in (origin.get("rpy", "0 0 0") if origin is not None
                                  else "0 0 0").split()]
        axis_el = j.find("axis")
        axis = [float(v) for v in (axis_el.get("xyz", "1 0 0") if axis_el is not None
                                   else "1 0 0").split()]
        joints[j.get("name")] = {
            "type": j.get("type"),
            "parent": j.find("parent").get("link"),
            "child": j.find("child").get("link"),
            "xyz": np.array(xyz), "rpy": np.array(rot), "axis": np.array(axis),
        }
    return joints


def fk(joints: dict[str, dict], q: dict[str, float], root_link: str,
       target_link: str) -> np.ndarray:
    """Transform from root_link to target_link, walking the chain child -> parent."""
    by_child = {j["child"]: (name, j) for name, j in joints.items()}
    chain = []
    link = target_link
    while link != root_link:
        if link not in by_child:
            sys.exit(f"link '{link}' has no parent joint; chain to '{root_link}' is broken")
        name, j = by_child[link]
        chain.append((name, j))
        link = j["parent"]

    T = np.eye(4)
    for name, j in reversed(chain):
        step = homogeneous(rpy(*j["rpy"]), j["xyz"])
        if j["type"] in ("revolute", "continuous"):
            step = step @ homogeneous(axis_angle(j["axis"], q.get(name, 0.0)), np.zeros(3))
        elif j["type"] == "prismatic":
            step = step @ homogeneous(np.eye(3), j["axis"] * q.get(name, 0.0))
        T = T @ step
    return T


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", nargs=3, type=float, default=[0.4, 0.1, 0.3],
                    help="goal position the IK request asked for")
    ap.add_argument("--urdf", default=os.path.join(
        os.environ.get("CONDA_PREFIX", ""), "share",
        "isaac_ros_cumotion_robot_description", "urdf", "ur5e_robotiq_2f_85.urdf"))
    ap.add_argument("--link", default=TARGET_LINK)
    ap.add_argument("joints", nargs=6, type=float, help="the six arm joint values, radians")
    args = ap.parse_args()

    joints = load_joints(args.urdf)
    q = dict(zip(ARM_JOINTS, args.joints))
    T = fk(joints, q, "base_link", args.link)

    goal = np.array(args.goal)
    pos = T[:3, 3]
    err = float(np.linalg.norm(pos - goal))

    print(f"urdf          {os.path.basename(args.urdf)}")
    print(f"joints        {[round(v, 6) for v in args.joints]}")
    print(f"fk({args.link})".ljust(14) + f"[{pos[0]: .6f} {pos[1]: .6f} {pos[2]: .6f}]")
    print(f"goal          [{goal[0]: .6f} {goal[1]: .6f} {goal[2]: .6f}]")
    print(f"position err  {err * 1000:.3f} mm")

    # The IK request asked for orientation (x=1, y=0, z=0, w=0): a half turn about X, so
    # the tool's own +Z points along world -Z.
    z_axis = T[:3, 2]
    print(f"tool +Z       [{z_axis[0]: .4f} {z_axis[1]: .4f} {z_axis[2]: .4f}]"
          f"   (goal: [0 0 -1], dot = {float(z_axis @ np.array([0, 0, -1.0])): .6f})")

    ok = err < 1e-3
    print(f"\n{'ok' if ok else 'FAIL'}: gripper is {err * 1000:.3f} mm from the requested pose")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
