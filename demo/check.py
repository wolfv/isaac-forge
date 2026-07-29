#!/usr/bin/env python3
"""Verify the Isaac-ROS-on-RoboStack overlay, layer by layer.

Each check is independent, so a failure tells you exactly which layer broke
rather than just "the demo does not work".
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys

PREFIX = os.environ.get("CONDA_PREFIX")
if not PREFIX:
    sys.exit("run me through pixi: pixi run check")

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


# 1. Dynamic linking: does the proprietary NITROS core resolve against
#    RoboStack's rclcpp/rcl/rcutils/rmw? This is the whole ABI question.
try:
    ctypes.CDLL(f"{PREFIX}/lib/libisaac_ros_nitros.so", mode=ctypes.RTLD_GLOBAL)
    record("NITROS core links against RoboStack", True)
except OSError as exc:
    record("NITROS core links against RoboStack", False, str(exc))

# 2. ament index: does ROS 2 discover the overlaid packages?
try:
    out = subprocess.run(
        ["ros2", "pkg", "list"], capture_output=True, text=True, timeout=120
    ).stdout.split()
    isaac = [p for p in out if p.startswith(("isaac_", "gxf_isaac", "negotiated"))]
    record("ROS 2 discovers Isaac packages", len(isaac) >= 15, f"{len(isaac)} packages")
except Exception as exc:  # noqa: BLE001
    record("ROS 2 discovers Isaac packages", False, str(exc))

# 3. pluginlib: are the composable node components registered?
try:
    out = subprocess.run(
        ["ros2", "component", "types"], capture_output=True, text=True, timeout=120
    ).stdout
    comps = [l.strip() for l in out.splitlines() if "isaac_ros" in l and "::" in l]
    record("Composable node components registered", len(comps) >= 8, f"{len(comps)} components")
except Exception as exc:  # noqa: BLE001
    record("Composable node components registered", False, str(exc))

# 3b. Host leakage: a node library can appear to load only because the host OS
#     happens to ship a matching soname (Fedora 43 has boost 1.83, which is what
#     the Isaac binaries want, while the conda env has 1.90). That is not
#     portable, so treat any resolution outside $CONDA_PREFIX as a failure.
def leaked(lib: str) -> list[str]:
    gxf = subprocess.run(
        ["bash", "-c",
         f'find "{PREFIX}/share" -name "*.so" -path "*gxf*" -printf "%h\\n" 2>/dev/null'
         " | sort -u | tr '\\n' ':'"],
        capture_output=True, text=True,
    ).stdout
    env = {**os.environ, "LD_LIBRARY_PATH": f"{gxf}{PREFIX}/lib"}
    out = subprocess.run(
        ["ldd", f"{PREFIX}/lib/{lib}"], capture_output=True, text=True, env=env, timeout=60
    ).stdout
    bad = []
    for line in out.splitlines():
        if "=>" not in line:
            continue
        soname, _, path = (p.strip() for p in line.partition("=>"))
        path = path.split(" (")[0].strip()
        if not path or not path.startswith("/"):
            continue
        # ld.so and the libc family always come from the host; that is expected.
        if soname.split(".so")[0] in (
            "linux-vdso", "libc", "libm", "libdl", "librt", "libpthread",
            "libgcc_s", "ld-linux-x86-64", "libstdc++",
        ):
            continue
        if not path.startswith(PREFIX):
            bad.append(f"{soname} <- {path}")
    return bad

try:
    leaks = leaked("libvisual_slam_node.so")
    record(
        "No host-library leakage (visual_slam)",
        not leaks,
        "; ".join(leaks) if leaks else "",
    )
except Exception as exc:  # noqa: BLE001
    record("No host-library leakage (visual_slam)", False, str(exc))

# 4. CUDA: is the host driver new enough for the CUDA 13 runtime Isaac needs?
#    Isaac ROS 4.5 requires driver >= 580; anything older reports < 13000 here.
try:
    drv = ctypes.CDLL("libcuda.so.1")
    ver = ctypes.c_int(0)
    drv.cuDriverGetVersion(ctypes.byref(ver))
    ok = ver.value >= 13000
    record(
        "NVIDIA driver supports CUDA 13",
        ok,
        f"driver exposes CUDA {ver.value // 1000}.{(ver.value % 1000) // 10}, need >= 13.0",
    )
except OSError as exc:
    record("NVIDIA driver supports CUDA 13", False, f"libcuda not loadable: {exc}")

width = max(len(n) for n, _, _ in results)
print()
for name, ok, detail in results:
    print(f"  [{'PASS' if ok else 'FAIL'}]  {name:<{width}}  {detail}")

gpu_ok = results[-1][1]
pkg_ok = all(ok for _, ok, _ in results[:-1])
print()
if pkg_ok and gpu_ok:
    print("  packaging and GPU both good -- 'pixi run demo' should fully work.")
elif pkg_ok:
    print("  packaging is good; only the GPU driver is too old.")
    print("  Isaac ROS 4.5 needs driver >= 580. Nodes will load but fail at CUDA init.")
else:
    print("  packaging problem -- see the failing layer above.")
sys.exit(0 if pkg_ok else 1)
