#!/usr/bin/env python3
"""Prove the pose-estimation packages are usable, not merely installed.

Four levels, cheapest first:

  1. every package is visible in the ament index,
  2. the one generated interface (FoundationPose's SwitchMesh service) imports,
  3. the asset-install script FoundationPose's models come from is on disk and runnable,
  4. every C++ composable node the seven packages register actually dlopens inside a
     component container.

(4) is the one that matters, and it matters most for isaac_ros_foundationpose: that
package compiles nvdiffrast's CUDA rasteriser with CUDA_SEPARABLE_COMPILATION, so it
carries a device-linked blob, and a toolkit/runtime mismatch there is invisible until
dlopen -- which is exactly how the nvcc 13.0 vs cudart 13.3 problem in variants.yaml
surfaced. The decoders in dope and centerpose link RoboStack's OpenCV rather than the
4.6 NVIDIA built against, which is the other thing only a real load can settle.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

PACKAGES = [
    "isaac_ros_pose_proc",
    "isaac_ros_dope",
    "isaac_ros_centerpose",
    "isaac_ros_foundationpose",
    "isaac_ros_foundationpose_models_install",
    "isaac_ros_tensor_proc",
    "isaac_ros_dnn_image_encoder",
]

# Loading into a uniquely named container rather than the default /ComponentManager.
# Every component_container on the DDS domain answers to that default name, and the other
# Isaac environments in this repo leave containers running, so addressing by the default
# name silently sends load requests to a prefix that does not have these packages
# installed. The failure it produces -- "Could not find requested resource in ament
# index" -- is indistinguishable from a real registration bug, and it is intermittent,
# because which container answers depends on discovery order.
CONTAINER = "pose_check_container"

# Every component the seven packages register, as named in their
# rclcpp_components_register_nodes() calls, with the parameters (if any) their
# constructors insist on. Two of them validate in the initialiser list and throw:
# CenterPoseDecoderNode wants a 2-element output_field_size, NormalizeNode wants a
# non-zero input_image_width. Those are genuine required parameters, not packaging
# problems, so pass plausible values rather than skip the node -- a component that only
# loads with no parameters set is a weaker result than one that loads configured.
#
# FoundationPoseNode needs nothing: it resolves its model paths lazily, so it constructs
# without the ONNX files present. That is what lets this check run with no NGC download.
#
# The CV-CUDA nodes also reserve a device memory pool in their constructors, defaulting to
# 40 blocks of 1920x1200x4 -- ~369 MB each, and all 21 components land in one container, on
# a GPU that may already be busy. So each of those gets a small pool: the point is that the
# CUDA allocation path works, and one block proves that as well as forty do.
POOL = ["memory_pool_num_blocks:=1", "memory_pool_block_size:=1048576"]

COMPONENTS = [
    ("isaac_ros_pose_proc", "nvidia::isaac_ros::pose_proc::AveragingFilterNode"),
    ("isaac_ros_pose_proc", "nvidia::isaac_ros::pose_proc::Detection3DArrayToPoseNode"),
    ("isaac_ros_pose_proc", "nvidia::isaac_ros::pose_proc::DistanceSelectorNode"),
    ("isaac_ros_pose_proc", "nvidia::isaac_ros::pose_proc::OutlierFilterNode"),
    ("isaac_ros_pose_proc", "nvidia::isaac_ros::pose_proc::PoseArrayToPoseNode"),
    ("isaac_ros_pose_proc", "nvidia::isaac_ros::pose_proc::StabilityFilterNode"),
    ("isaac_ros_dope", "nvidia::isaac_ros::dope::DopeDecoderNode"),
    ("isaac_ros_centerpose", "nvidia::isaac_ros::centerpose::CenterPoseDecoderNode",
     ["output_field_size:=[128,128]", "cuboid_scaling_factor:=1.0",
      "score_threshold:=0.3"] + POOL),
    ("isaac_ros_centerpose", "nvidia::isaac_ros::centerpose::CenterPoseVisualizerNode"),
    ("isaac_ros_foundationpose", "nvidia::isaac_ros::foundationpose::FoundationPoseNode"),
    ("isaac_ros_foundationpose",
     "nvidia::isaac_ros::foundationpose::FoundationPoseTrackingNode"),
    ("isaac_ros_foundationpose", "nvidia::isaac_ros::foundationpose::Detection2DArrayFilter"),
    ("isaac_ros_foundationpose", "nvidia::isaac_ros::foundationpose::Detection2DToMask"),
    ("isaac_ros_foundationpose", "nvidia::isaac_ros::foundationpose::Selector"),
    ("isaac_ros_tensor_proc", "nvidia::isaac_ros::dnn_inference::InterleavedToPlanarNode",
     ["input_tensor_shape:=[1,3,64,64]"] + POOL),
    ("isaac_ros_tensor_proc", "nvidia::isaac_ros::dnn_inference::ReshapeNode"),
    ("isaac_ros_tensor_proc", "nvidia::isaac_ros::dnn_inference::ImageToTensorNode"),
    ("isaac_ros_tensor_proc", "nvidia::isaac_ros::dnn_inference::ImageTensorNormalizeNode"),
    ("isaac_ros_tensor_proc", "nvidia::isaac_ros::dnn_inference::NormalizeNode",
     ["input_image_width:=64", "input_image_height:=64"] + POOL),
    ("isaac_ros_tensor_proc", "nvidia::isaac_ros::dnn_inference::TensorPairSyncNode", POOL),
    ("isaac_ros_dnn_image_encoder",
     "nvidia::isaac_ros::dnn_inference::DnnImageEncoderNode",
     ["input_image_width:=64", "input_image_height:=64",
      "network_image_width:=64", "network_image_height:=64"] + POOL),
]

failures = 0


def report(ok: bool, what: str, detail: str = "") -> None:
    global failures
    if not ok:
        failures += 1
    print(f"  {'ok  ' if ok else 'FAIL'}  {what}{': ' + detail if detail else ''}")


print("ament index")
listed = subprocess.run(["ros2", "pkg", "list"], capture_output=True, text=True).stdout.split()
for pkg in PACKAGES:
    report(pkg in listed, f"ros2 pkg list sees {pkg}")

print("\ngenerated interfaces")
try:
    from isaac_ros_foundationpose.srv import SwitchMesh  # noqa: F401
    report(True, "service type isaac_ros_foundationpose/srv/SwitchMesh")
except Exception as exc:  # noqa: BLE001 -- any import failure is a packaging failure
    report(False, "service type SwitchMesh", f"{type(exc).__name__}: {exc}")

print("\nasset install script")
# The patch in recipes/ros-jazzy-isaac-ros-foundationpose-models-install replaces
# upstream's build-time download with this script plus its ament resource. Check both,
# since nothing else in the package would notice if either went missing.
prefix = os.environ.get("CONDA_PREFIX", sys.prefix)
script = os.path.join(
    prefix, "lib/isaac_ros_foundationpose_models_install/install_foundationpose_models.sh")
report(os.access(script, os.X_OK), "install_foundationpose_models.sh present and executable")
resource = os.path.join(
    prefix, "share/ament_index/resource_index/install_foundationpose_models",
    "isaac_ros_foundationpose_models_install")
report(os.path.isfile(resource), "ament resource install_foundationpose_models registered")

print(f"\nC++ components (dlopen into a live container) -- {len(COMPONENTS)} to load")
container = subprocess.Popen(
    ["ros2", "run", "rclcpp_components", "component_container",
     "--ros-args", "-r", f"__node:={CONTAINER}"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    # Wait for *this* container to be discoverable, not merely for the CLI to exit 0 --
    # `ros2 component list` succeeds with empty output when no container is up at all, so
    # a returncode check races straight past the container's startup.
    ready = False
    for _ in range(60):
        out = subprocess.run(["ros2", "component", "list"], capture_output=True, text=True)
        if CONTAINER in out.stdout:
            ready = True
            break
        time.sleep(0.5)
    report(ready, f"container /{CONTAINER} is up")

    for entry in COMPONENTS:
        pkg, cls = entry[0], entry[1]
        params = entry[2] if len(entry) > 2 else []
        cmd = ["ros2", "component", "load", f"/{CONTAINER}", pkg, cls]
        for p in params:
            cmd += ["-p", p]
        # Bounded and retried once. `ros2 component load` is a fresh process that has to
        # discover the container's service itself, and it waits forever if it does not --
        # so an unbounded call can wedge the whole check with no output at all. The retry is
        # for the first load specifically: `ros2 component list` seeing the container does
        # not mean a *new* participant will discover its services on the first attempt, and
        # on a machine already carrying a dozen DDS participants that first request is the
        # one that gets lost. A timeout is therefore not evidence about the package; a
        # timeout twice in a row is.
        loaded, detail = False, ""
        for attempt in (1, 2):
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                loaded = "Loaded component" in out.stdout
                if loaded:
                    break
                lines = (out.stdout + out.stderr).strip().splitlines()
                detail = lines[-1] if lines else "no output"
                break  # a real error, not a discovery race -- do not retry
            except subprocess.TimeoutExpired:
                detail = f"timed out after 60s waiting for the load service ({attempt}x)"
        note = f" ({', '.join(params)})" if params else ""
        report(loaded, f"load {cls.split('::')[-1]}{note}", detail)
finally:
    container.terminate()
    container.wait(timeout=20)

print("\nFAILED" if failures else "\nall checks passed")
sys.exit(1 if failures else 0)
