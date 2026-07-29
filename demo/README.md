# Runnable demo: Isaac ROS on RoboStack

Proves that NVIDIA's Isaac ROS binaries compose with RoboStack's ROS 2 Jazzy conda packages,
by standing up an `rclcpp` component container and loading a real Isaac ROS node into it.

```bash
cd demo
./setup.sh        # or: pixi run setup
pixi run check    # layer-by-layer verification
pixi run demo     # load nvidia::isaac_ros::image_proc::ResizeNode
pixi run e2e      # push a real image through the GPU and verify the result
```

"Container" here is ROS's `rclcpp_components` **node** container — a process that composable nodes
get loaded into. There is no Docker anywhere in this project; that is the point.

## What it builds

`setup.sh` resolves the combined apt dependency closure of five Isaac ROS packages —
**34 debs** — downloads them, and overlays them onto the pixi environment together with the `vpi`
package from `../recipes/vpi`. Everything ROS-side comes from `robostack-jazzy`; CUDA comes from
conda-forge.

| Target | Adds |
|---|---|
| `isaac_ros_image_proc` | resize, crop, pad, flip, format-convert, normalize, alpha-blend, rectify |
| `isaac_ros_stereo_image_proc` | disparity, disparity→depth, point cloud |
| `isaac_ros_depth_image_proc` | XYZ / XYZRGB point clouds, metric convert, depth→color align |
| `isaac_ros_visual_slam` | cuVSLAM visual SLAM |
| `isaac_ros_apriltag` | GPU AprilTag detection |

That is 17 registered composable node components across 30 ROS packages, for 34 debs — the
closures overlap heavily, so the four extra targets cost only 11 debs beyond `image_proc` alone.

This deliberately shortcuts the per-package repack recipes. The ABI question is identical either
way, so proving it with an overlay first avoids writing 23 recipes against an unverified premise.

## Result on this machine

Driver 580.173.02 / CUDA 13.0 / RTX 4060.

```
  [PASS]  NITROS core links against RoboStack
  [PASS]  ROS 2 discovers Isaac packages         30 packages
  [PASS]  Composable node components registered  17 components
  [FAIL]  No host-library leakage (visual_slam)  libboost_thread.so.1.83.0 <- /lib64/...
  [PASS]  NVIDIA driver supports CUDA 13         driver exposes CUDA 13.0, need >= 13.0
```

### It actually computes on the GPU

`pixi run e2e` publishes a synthetic 640x480 rgb8 colour ramp on `/image`, and reads back
`/resize/image`:

```
[INFO] [ResizeNode]: [ResizeNode] ResizeNode initialized
publishing 640x480 rgb8 on /image, waiting for /resize/image ...
received /resize/image: 320x240 rgb8, 230400 bytes
content check: min=0 max=254 mean=127.3 -- real resampled pixel data

PASS: 640x480 -> 320x240 on the GPU, after 1 published frames
```

The content check matters: a uniform buffer would mean bytes moved but nothing was computed. Real
resampled pixel data means the full chain ran — RoboStack `rclpy` → NVIDIA's NITROS node →
CV-CUDA/VPI on the GPU → back out as a ROS message.

### Five Isaac nodes running at once, including cuVSLAM

```
$ ros2 node list
/visual_slam  /apriltag_node  /disparity_node  /PointCloudXyzNode  /ResizeNode
```

From the node container log:

```
[INFO] [visual_slam]:   cuVSLAM version: 15.0.0+74f0e317-modified
[INFO] [visual_slam]:   Tracking mode: Multicamera
[INFO] [visual_slam]:   Time taken by cuvslam::WarmUpGPU(): 0.003589
[INFO] [apriltag_node]: Using cuAprilTag implementation.
```

`cuvslam::WarmUpGPU()` returning in 3.6 ms is cuVSLAM initialising CUDA for real — the proprietary
NVIDIA SLAM library, loaded from a conda prefix, linked against RoboStack's ROS.

Load results for the five headline nodes:

| Node | Result |
|---|---|
| `ResizeNode` | runs, verified end-to-end on GPU |
| `VisualSlamNode` | loads, cuVSLAM 15.0.0 warms up the GPU |
| `AprilTagNode` | loads, cuAprilTag active |
| `DisparityNode` | loads |
| `PointCloudXyzNode` | loads |
| `RectifyNode` | **blocked** — `libopencv_stitching.so.406` |

### AprilTag, with Isaac's own message types


```
$ pixi run demo nvidia::isaac_ros::apriltag::AprilTagNode isaac_ros_apriltag
    Loaded component 1 into '/isaac_container' container node as '/apriltag_node'
    [INFO] [apriltag_node]: Using cuAprilTag implementation.

$ ros2 node info /apriltag_node
  Subscribers:
    /camera_info: sensor_msgs/msg/CameraInfo
    /image: sensor_msgs/msg/Image
  Publishers:
    /tag_detections: isaac_ros_apriltag_interfaces/msg/AprilTagDetectionArray
    /tf: tf2_msgs/msg/TFMessage
```

Note the publisher type: `isaac_ros_apriltag_interfaces/msg/AprilTagDetectionArray`. That is a
further ABI confirmation — the `rosidl` typesupport libraries NVIDIA generated against Ubuntu's
`rosidl` interoperate with RoboStack's.

### For the record: what an under-580 driver looks like

Before the driver was fixed (575, then a mis-installed 560), this is how far it got — worth keeping
because it isolates the packaging layers from GPU execution:

```
[INFO] Load Library: .../lib/libresize_node.so
[INFO] Found class: rclcpp_components::NodeFactoryTemplate<nvidia::isaac_ros::image_proc::ResizeNode>
[INFO] Instantiate class: rclcpp_components::NodeFactoryTemplate<nvidia::isaac_ros::image_proc::ResizeNode>
[ERROR] Component constructor threw an exception: Failed to create CUDA stream,
        cuda_error: cudaErrorInsufficientDriver
```

Read that sequence carefully — it is the whole point:

1. **`Load Library` succeeded.** `libresize_node.so` and its entire transitive closure resolved,
   including proprietary NITROS and GXF linking against RoboStack's `rclcpp`, `rcl`, `rcutils`
   and `rmw`. This is the claim that mattered, confirmed at runtime rather than by `ldd`.
2. **`Found class` succeeded.** The ament index and `pluginlib` registration survived the move
   from `/opt/ros/jazzy` into a conda prefix.
3. **`Instantiate class`** ran the constructor.
4. The *only* failure was creating a CUDA stream.

So the packaging, linking and ROS integration layers are all correct. The single remaining blocker
is the host GPU driver.

## Input data for a real demo

Two sources, both usable without credentials:

- **In-repo git-lfs bags** in `isaac_ros_visual_slam/test/test_cases/rosbags/`:
  `rosbag2_rs455_rgbd.mcap` (**106 MB**, RealSense D455 RGBD) and `r2b_galileo_0.mcap`
  (**493 MB**, the official r2b Galileo Nova multi-camera set, plus `isaac_calibration.urdf` and a
  prebuilt cuVSLAM map). Fetch with `../scripts/clone.sh --lfs`.
- **NGC**, verified public — no auth, plain HTTP 200:
  ```
  https://api.ngc.nvidia.com/v2/resources/org/nvidia/team/isaac/r2bdataset2024/1/files?redirect=true&path=r2b_galileo/metadata.yaml
  ```
  This is what `isaac_ros_r2b_galileo` fetches via `FetchContent`.

`ros-jazzy-rosbag2-storage-mcap` is in the env, so the bags can be replayed directly. For
visualisation `foxglove_bridge` is installed too, which is easier than rviz here — it serves over a
websocket to a browser, so no local GL context is needed.

## GPU requirement

Isaac ROS 4.5 is built against CUDA 13.0, which needs **NVIDIA driver >= 580**. Check with:

```bash
nvidia-smi --query-gpu=name,driver_version --format=csv
```

Forward compatibility does not help if you are short: the `cuda-compat` packages that let an older
driver run a newer CUDA runtime are supported only on datacenter GPUs, not GeForce. A driver upgrade
is the only route.

On Fedora, `../scripts/fix_nvidia_driver.sh` does it. It exists because GNOME Software installed
`nvidia-driver-560.35.05-1.fc39` on this Fedora **43** box — two stale NVIDIA repos
(`cuda-fedora39`, `cuda-fedora41`) were enabled, and the fc39 driver is DKMS-based and cannot build
against kernel 7.1.5. The result was `dkms status: added` but no `nvidia.ko`, nouveau driving the
GPU, and `cuInit()` returning 100 (`CUDA_ERROR_NO_DEVICE`).

Two things that made the fix non-obvious:

- `dnf install --allowerasing` was not enough. The blockers were raw **RPM file conflicts** on
  `/usr/lib64/libnvidia-ml.so.1` and `libnvidia-cfg.so.1`, owned by `libnvidia-ml` and
  `libnvidia-cfg`. Those packages do not obsolete the new ones, so dnf had no basis to remove them.
  They also do not match a `nvidia-*` prefix, which is why a first pass at the removal list missed
  them. The script removes every installed package with `nvidia` anywhere in the name except
  Fedora's own `nvidia-gpu-firmware`.
- Three driver versions were tangled together: 560 (fc39), a 575 (fc41) `libnvidia-gpucomp`
  leftover, and fc43 firmware.

Verify the module built **before** rebooting — this is the step that silently failed:

```bash
sudo akmods --force && sudo modinfo -F version nvidia   # expect 580.x
```

## Node-library load matrix

Loading every node library directly with `dlopen` isolates linking from GPU execution:

```
  libresize_node.so                  LOADS
  libapriltag_node.so                LOADS
  libdisparity_node.so               LOADS
  libpoint_cloud_xyz_node.so         LOADS
  libimage_format_converter_node.so  LOADS
  libcrop_node.so                    LOADS
  libvisual_slam_node.so             LOADS *
  librectify_node.so                 blocked by libopencv_stitching.so.406
  libalign_depth_to_color_node.so    blocked by libopencv_stitching.so.406
```

`*` — `libvisual_slam_node.so` links only because Fedora 43 happens to ship
`libboost_thread.so.1.83.0` in `/lib64`, which the loader finds. The conda env has Boost **1.90**.
That is host leakage, not a working package, so `check.py` reports it as a failure. `cuVSLAM` and
`libcusolver.so.12` do resolve properly from the prefix.

## Two soname gaps

Both are the same shape: NVIDIA built against Ubuntu noble's versions, RoboStack/conda-forge ship
different ones.

| Library | Isaac needs | conda side | Affects |
|---|---|---|---|
| OpenCV | `libopencv_*.so.406` (4.6) | 4.13 / 5.0 | `rectify`, `align_depth_to_color` |
| Boost | `libboost_*.so.1.83.0` | 1.90 (RoboStack mutex wants 1.84) | `visual_slam` |

Pinning `libboost = "1.83.*"` does not work — RoboStack's `ros2-distro-mutex` constrains
`libboost 1.84.*`, so the solve fails.

For both, the options are a version-specific compat package providing just the old sonames, or
source-building the affected packages. `isaac_ros_visual_slam` is Apache-2.0 with real source (10
`.cpp`) and cuVSLAM enters as an imported `.so`, so source-building that one wrapper against
RoboStack's Boost is clean and cheap — a good concrete argument for the hybrid approach in
`../FINDINGS.md` §6.

## Known rough edges

These are demo shortcuts, not things the real recipes should inherit:

- **RUNPATH.** The debs hard-code `/opt/ros/jazzy/share/**/gxf/lib/...`, which does not exist in a
  conda prefix, so `activate.d/zz-isaac-gxf.sh` prepends those directories to `LD_LIBRARY_PATH`.
  Repack recipes should rewrite the RPATH to `$ORIGIN`-relative paths at build time instead.
- **Three deb layouts.** `scripts/overlay_debs.sh` handles all three the closure actually uses:
  `opt/ros/jazzy/{lib,share,include}`, the Debian multiarch `lib/x86_64-linux-gnu/` (used by
  `ros-jazzy-negotiated`), and NVIDIA's SDK layout `opt/nvidia/<sdk>/lib` (used by `libcvcuda0`
  and VPI).
- **OpenCV.** `ResizeNode` does not need OpenCV, so this closure sidesteps the OpenCV 4.6-vs-5.0
  soname mismatch. `RectifyNode` *does* link `libopencv_*.so.406` and will not load until that is
  resolved — see `../FINDINGS.md` §5.
