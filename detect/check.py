#!/usr/bin/env python3
"""Prove the object-detection packages are usable, not merely installed.

Same four levels as pose/check.py, and the same reasons: the ament index sees the
packages, the generated interfaces import, the asset scripts are on disk, and every C++
composable node actually dlopens inside a component container.

Two things are worth checking here specifically. The three *_models_install packages
carry no code at all -- their entire payload is an asset script plus its ament resource,
and both come from the install_isaac_ros_asset() rewrite in scripts/gen_source.py rather
than from upstream, so if that rewrite ever stops matching, nothing else would notice.
And the decoders link RoboStack's OpenCV rather than the 4.6 NVIDIA built against, which
only a real load settles.

The nodes here decode tensors that a TensorRT node produces upstream. They load and
construct without it -- which is what this check establishes -- but a full detection
pipeline still needs TensorRT. See README.md.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

PACKAGES = [
    "isaac_ros_detectnet",
    "isaac_ros_yolov8",
    "isaac_ros_rtdetr",
    "isaac_ros_grounding_dino",
    "isaac_ros_grounding_dino_interfaces",
    "isaac_ros_rtdetr_models_install",
    "isaac_ros_grounding_dino_models_install",
    "isaac_ros_peoplenet_models_install",
    "isaac_ros_dnn_image_encoder",
    "isaac_ros_tensor_proc",
]

# A container name of this environment's own, not the default /ComponentManager. Every
# component_container on the DDS domain answers to that default, and the other check
# environments in this repo leave containers running, so addressing it sends load requests
# to a prefix without these packages installed -- which fails as "Could not find requested
# resource in ament index" and reads exactly like a registration bug. See pose/README.md.
CONTAINER = "detect_check_container"

# The CV-CUDA nodes reserve a device memory pool in their constructors, defaulting to 40
# blocks of 1920x1200x4 -- ~369 MB each, on a GPU that may already be busy. A small pool
# still exercises the CUDA allocation path, which is the thing worth proving.
POOL = ["memory_pool_num_blocks:=1", "memory_pool_block_size:=1048576"]

COMPONENTS = [
    ("isaac_ros_detectnet", "nvidia::isaac_ros::detectnet::DetectNetDecoderNode"),
    ("isaac_ros_yolov8", "nvidia::isaac_ros::yolov8::YoloV8DecoderNode"),
    ("isaac_ros_rtdetr", "nvidia::isaac_ros::rtdetr::RtDetrPreprocessorNode", POOL),
    ("isaac_ros_rtdetr", "nvidia::isaac_ros::rtdetr::RtDetrDecoderNode"),
    ("isaac_ros_grounding_dino",
     "nvidia::isaac_ros::grounding_dino::GroundingDinoPreprocessorNode"),
    ("isaac_ros_grounding_dino",
     "nvidia::isaac_ros::grounding_dino::GroundingDinoDecoderNode"),
]

# (package, asset name). The asset name is also the script's basename -- that equality is
# what the generator's rewrite relies on, so checking it here checks the rewrite.
ASSETS = [
    ("isaac_ros_rtdetr_models_install", "install_rtdetr_models"),
    ("isaac_ros_grounding_dino_models_install", "install_grounding_dino_models"),
    ("isaac_ros_peoplenet_models_install", "install_peoplenet_amr_rs"),
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
    from isaac_ros_grounding_dino_interfaces.srv import GetTextTokens  # noqa: F401
    from isaac_ros_grounding_dino_interfaces.srv import SetPrompt  # noqa: F401
    report(True, "service types SetPrompt, GetTextTokens")
except Exception as exc:  # noqa: BLE001 -- any import failure is a packaging failure
    report(False, "grounding_dino_interfaces service types", f"{type(exc).__name__}: {exc}")

print("\nasset install scripts (the install_isaac_ros_asset rewrite's payload)")
prefix = os.environ.get("CONDA_PREFIX", sys.prefix)
for pkg, asset in ASSETS:
    script = os.path.join(prefix, "lib", pkg, f"{asset}.sh")
    report(os.access(script, os.X_OK), f"{asset}.sh present and executable")
    resource = os.path.join(prefix, "share/ament_index/resource_index", asset, pkg)
    report(os.path.isfile(resource), f"ament resource {asset} registered")

print(f"\nC++ components (dlopen into a live container) -- {len(COMPONENTS)} to load")
container = subprocess.Popen(
    ["ros2", "run", "rclcpp_components", "component_container",
     "--ros-args", "-r", f"__node:={CONTAINER}"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    # Wait for *this* container, not merely for the CLI to exit 0 -- `ros2 component list`
    # succeeds with empty output when nothing is up, so a returncode check races straight
    # past startup.
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
        # discover the container's service itself and waits forever if it does not, so an
        # unbounded call can wedge the whole check with no output at all. The retry is for
        # the first load: a new participant does not always discover services on its first
        # attempt on a busy machine, so one timeout is not evidence about the package --
        # two in a row is.
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
