# isaac-forge

`isaac-forge` packages Isaac ROS 4.5.0 for ROS 2 Jazzy as conda packages. The
packages work alongside [RoboStack](https://robostack.github.io/) and can be installed with
[Pixi](https://pixi.sh/) on x86_64 Linux and Jetson/ARM64.

## Using the packages

The packages are published in the public
[`isaac-forge` channel on prefix.dev](https://prefix.dev/channels/isaac-forge). A Pixi
environment should use these channels, in this order:

1. `isaac-forge` for Isaac ROS and the few dependencies packaged here
2. `robostack-jazzy` for ROS 2 Jazzy
3. `conda-forge` for everything else

Here is a small environment for the Isaac ROS YOLOv8 pipeline:

```toml
# pixi.toml
[workspace]
channels = [
  "https://prefix.dev/isaac-forge",
  "https://prefix.dev/robostack-jazzy",
  "conda-forge",
]
platforms = [{ platform = "linux-64", glibc = "2.38" }]

[dependencies]
python = "3.12.*"
ros-jazzy-ros-base = "*"
ros-jazzy-isaac-ros-dnn-image-encoder = "4.5.*"
ros-jazzy-isaac-ros-tensor-rt = "4.5.*"
ros-jazzy-isaac-ros-yolov8 = "4.5.*"
```

Install it and run ROS commands through Pixi:

```bash
pixi install
pixi run ros2 pkg prefix isaac_ros_yolov8
pixi run ros2 component types | grep -E 'TensorRTNode|YoloV8DecoderNode'
```

For a Jetson, use `linux-aarch64` instead of `linux-64`. The packages target the Ubuntu
24.04 glibc floor (`2.38`) and the CUDA 13 stack, so GPU workloads also need a compatible
NVIDIA driver. Pixi installs the user-space CUDA libraries; it does not install the host
driver.

Package names follow the usual RoboStack convention: the ROS package
`isaac_ros_visual_slam`, for example, is named
`ros-jazzy-isaac-ros-visual-slam`. You can browse or search all available names on the
[channel page](https://prefix.dev/channels/isaac-forge). Pixi resolves the package's NITROS,
GXF, ROS, CUDA, and other library dependencies automatically.

For a complete working project, see [`yolo/`](yolo/README.md). Its `pixi.toml` consumes the
public channel and runs YOLOv8 TensorRT inference on an image, video, webcam, or RTSP stream.

[![Isaac Forge YOLOv8 demo](https://img.youtube.com/vi/DbLr-rPKjwo/maxresdefault.jpg)](https://www.youtube.com/watch?v=DbLr-rPKjwo)

## What is in the channel?

The channel currently has **226 package names for `linux-64`** and **213 for
`linux-aarch64`**. It contains:

- the NITROS and GXF foundations, including the NITROS ROS type adapters;
- VPI, TensorRT, Triton Server, cuVSLAM, cuAprilTags, and cuMotion;
- image, stereo, depth, tensor, and point-cloud processing;
- visual SLAM, nvblox, occupancy-grid localization, and AprilTag detection;
- YOLOv8, RT-DETR, DetectNet, DOPE, CenterPose, FoundationPose, ESS,
  FoundationStereo, U-Net, SegFormer, and Segment Anything packages;
- cuMotion, MoveIt integration, robot descriptions, manipulation bringup, and benchmark
  packages;
- cloud control, VDA5050, deployment, teleoperation, data recording, RealSense, ZED, and
  Unitree G1 integration;
- the Isaac ROS and ROS 2 benchmark harnesses, examples, interfaces, and a handful of
  open-source ROS dependencies not yet available from RoboStack Jazzy.

The `*-models-install` packages provide NVIDIA's asset download/install tooling. Model
weights and GPU-specific TensorRT engine plans are not baked into the conda packages.

There are currently 13 x86-only names: `libdcgm`, `nvv4l2`, the four H.264 packages,
`isaac_ros_image_proc`, the two PyNITROS packages, the Unitree recorder, the two visual
mapping packages, and `isaac_ros_visual_slam`. Their vendor payload or test closure is not
portable to the generic ARM build runner. The other 213 packages were built and tested
natively on ARM64 rather than cross-compiled or relabelled from x86_64.

## Examples and checks

The repository contains a few environments used to exercise different parts of the channel:

| Directory | What it runs or checks |
|---|---|
| [`yolo/`](yolo/README.md) | YOLOv8 with the public channel, TensorRT, and image/video visualization |
| [`demo/`](demo/README.md) | Image processing, visual SLAM, and AprilTag components |
| [`slam/`](slam/README.md) | NVDEC → CV-CUDA → cuVSLAM on NVIDIA's r2b Galileo dataset |
| [`manip/`](manip/README.md) | cuMotion GPU IK with an independent forward-kinematics check |
| [`pose/`](pose/README.md) | Pose-estimation packages and composable components |
| [`detect/`](detect/README.md) | Object detection components and TensorRT engine creation |
| [`bench/`](bench/README.md) | NVIDIA's benchmark harness running against the conda packages |

Most of the older check environments still point to `../output`, the local build channel.
To use published packages instead, replace that channel entry with
`https://prefix.dev/isaac-forge`, as shown in `yolo/pixi.toml`.

## Building the packages

You only need this repository if you want to build or change the packages. The recipes are
checked in, so a normal build does not clone NVIDIA's source repositories or regenerate
anything first.

```bash
git clone https://github.com/wolfv/isaac-forge.git
cd isaac-forge
pixi install

pixi run build                                  # resumable full build
pixi run build -- --recipe ros-jazzy-isaac-ros-nitros
pixi run test                                   # test packages in clean environments
```

Packages are written to `output/linux-64/`, `output/linux-aarch64/`, and `output/noarch/`.
Builds and tests are separate because a package's test environment may need another package
that is built later in the graph.

CUDA packages should be built and tested on the target architecture. On a native Jetson or
other ARM64 machine:

```bash
pixi run arm64-render
pixi run build -- --target linux-aarch64
pixi run test
```

Cross-targeting ARM64 from x86_64 is useful for rendering recipes and auditing dependency
solutions, but not for producing release packages. To build for only one Jetson GPU
architecture, set it explicitly, for example:

```bash
CUDA_ARCHITECTURES=87 pixi run build -- --target linux-aarch64
```

The `gen_*` scripts are maintainer tools for refreshing recipes, not build prerequisites:

```bash
./scripts/clone.sh
pixi run inventory
python scripts/gen_source.py --help
python scripts/gen_repack.py --help
```

## How the packaging is split

Most Isaac ROS packages in this channel are built from source against RoboStack. Some central
NVIDIA components have no published source, so they are packaged from pinned vendor payloads
instead. That binary foundation includes VPI, TensorRT, several GXF extensions, cuVSLAM,
cuAprilTags, and cuMotion. A small third group fills gaps in the current RoboStack Jazzy
channel.

Every vendor input is selected per architecture and checksum-verified. Git LFS objects are
fetched from their upstream media endpoints rather than packaging the pointer files. See
[`FINDINGS.md`](FINDINGS.md) for the dependency, ABI, source-availability, and licensing
work behind the recipes. Upstream problems and proposed fixes are collected in
[`ISSUES.md`](ISSUES.md) and [`upstream/`](upstream/README.md).

## Repository layout

```text
recipes/                 rattler-build recipes
scripts/build_all.sh     resumable build driver
scripts/test_all.sh      clean-environment package tests
scripts/gen_source.py    source-recipe generator
scripts/gen_repack.py    vendor-package recipe generator
packages.json            generated Isaac ROS package inventory
variants.yaml            shared CUDA, Python, and compiler pins
demo/, slam/, manip/     runnable GPU checks
pose/, detect/, yolo/    inference and component checks
bench/                   benchmark harness
output/                  local package channel (gitignored)
```

## Licensing

The channel contains both open-source software and proprietary NVIDIA components. Each recipe
records its package license and source. Redistribution details and the package-by-package
analysis are in [`FINDINGS.md`](FINDINGS.md).
