# `pose/` — the Isaac ROS pose-estimation stack

All **five** packages in
[`NVIDIA-ISAAC-ROS/isaac_ros_pose_estimation`](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_pose_estimation)
at `v4.5-0`, built from source against RoboStack, plus the two `isaac_ros_dnn_inference`
packages they need. Seven recipes, **21 composable nodes, all of them loading into one
container**.

```bash
cd pose && pixi run check
```

```
C++ components (dlopen into a live container) -- 21 to load
  ok    container /pose_check_container is up
  ok    load AveragingFilterNode
  ...
  ok    load FoundationPoseNode
  ok    load FoundationPoseTrackingNode
  ...
all checks passed
```

| package | what it contributes | components |
|---|---|---|
| `isaac_ros_foundationpose` | 6-DoF pose estimation + tracking, nvdiffrast CUDA rasteriser, `SwitchMesh` service | 5 |
| `isaac_ros_centerpose` | category-level pose decoder + visualiser | 2 |
| `isaac_ros_dope` | DOPE belief-map decoder | 1 |
| `isaac_ros_pose_proc` | pose filtering: averaging, outlier, stability, selectors | 6 |
| `isaac_ros_foundationpose_models_install` | the NGC asset script for FoundationPose's two ONNX models | — |
| `isaac_ros_tensor_proc` | CV-CUDA tensor plumbing (needed by the encoder) | 6 |
| `isaac_ros_dnn_image_encoder` | image → DNN input tensor | 1 |

## Why this repo said the whole set was blocked, and why it wasn't

`packages.json` marks four of the five with a `tensorrt` blocker and `isaac_ros_centerpose`
with `triton` as well. That is read off the manifests, and the manifests overstate it.

**`isaac_ros_foundationpose` never needed TensorRT to build.** TensorRT appears in its
`package.xml` only as an `<exec_depend>` — the launch graph composes a separate
`isaac_ros_tensor_rt` node to run the two engines. Nothing at configure or link time
touches it. What actually stood between it and a build was `isaac_ros_dnn_image_encoder`,
which is a `<depend>`; that lives in `isaac_ros_dnn_inference`, the repo where TensorRT
*does* live — but only in two of its four packages. `isaac_ros_tensor_proc` and
`isaac_ros_dnn_image_encoder` are CV-CUDA tensor plumbing with no inference engine
anywhere in them, and everything under those two was already built here. Two recipes
opened the door.

**`isaac_ros_dope` and `isaac_ros_centerpose` did not need it either**, and here the
manifest is simply wrong. Both declare `<depend>isaac_ros_tensor_rt` (centerpose also
`<depend>isaac_ros_triton`), and `ament_auto_find_build_dependencies()` turns every
`<depend>` into a REQUIRED `find_package` — so both are unbuildable without TensorRT
installed. Neither includes a single header from it:

```console
$ grep -rn 'tensor_rt\|nvinfer\|NvInfer\|triton' isaac_ros_dope/{src,include} \
                                                 isaac_ros_centerpose/{src,include}
$ # nothing
```

They are decoders. Each takes a `TensorList` off a topic and solves PnP on it, and is
written not to care which backend produced the tensors — which is exactly why centerpose
ships both a TensorRT and a Triton launch file. Demoting the two declarations to
`<exec_depend>`, which is what package format 3 has for a launch-graph relationship, makes
both build with nothing missing. Those are the two patches under
`recipes/ros-jazzy-isaac-ros-{dope,centerpose}/patches/`, both prepared for upstream, and
`ISSUES.md` #18 is the writeup.

So `tensorrt` was never a blocker on any of these five packages' **code**. It is still a
blocker on the reference **pipelines**: nothing here can run FoundationPose end to end
until an `isaac_ros_tensor_rt` node exists to serve the ONNX models, and RT-DETR
(`isaac_ros_rtdetr`) is what supplies FoundationPose's detection input. Seven built
packages and 21 loading components are not a working demo, and this directory does not
claim to be one — compare `slam/`, which tracks a real trajectory. What it claims is that
the packaging is done and correct, so the day TensorRT lands, the pose stack does not need
revisiting.

## Three things the build turned up

**The toolkit was three minors older than the runtime.** `isaac_ros_foundationpose` is the
first package here to set `CUDA_SEPARABLE_COMPILATION`, on the nvdiffrast/cudaraster
target, which means a real `nvlink` device-link step. It failed:

```
nvlink fatal : Input file '$PREFIX/targets/x86_64-linux/lib/libcudadevrt.a:
cuda_device_runtime.o' newer than toolkit (133 vs 130) (target: sm_80)
```

Every CUDA recipe here asks for `cuda-version 13.*` and resolves `cuda-cudart-dev
13.3.29`, while `variants.yaml` pinned `cuda_compiler_version: 13.0` — so nvcc had been
older than the cudart it compiled against in all 20 of them, invisibly, because none of
them device-linked. Moving the runtime down is not available (every built
`ros-jazzy-isaac-*` package carries `cuda-cudart >=13.3.29`, so a 13.0 host env does not
solve), so the pin moved up to `13.3`. **This changes the build hash of every CUDA
package in the repo** — see the note in `variants.yaml`.

**`libcvcuda-dev` has to be ≥ 0.16.** FoundationPose is also the first package here to
call `find_package(nvcv_types REQUIRED)` rather than naming the CV-CUDA libraries
directly. conda-forge's 0.16 ships `lib/cmake/{cvcuda,nvcv_types}/*-config.cmake`; the
0.14 deb repack this repo used before it ships only headers and two `.so` symlinks, and a
leftover copy of it in a local `output/` outranks conda-forge. The generator now pins the
floor so an unindexed leftover cannot win.

**The models are not downloaded at build time, on purpose.**
`install_isaac_ros_asset()` dry-runs its asset script at configure time (needs
`$ISAAC_ROS_WS`, so it aborts) and then makes `ALL` fetch two ONNX files from NGC behind a
EULA and run `trtexec` over them. The second half should not happen in a package build
regardless: a TensorRT engine plan is specialised to the GPU, driver and TensorRT version
that produced it. The recipe keeps the script and its ament resource and leaves the
download to the target system, which is how NVIDIA documents it anyway:

```bash
ros2 run isaac_ros_foundationpose_models_install install_foundationpose_models.sh
```

`ISSUES.md` #20 has the detail; that one is NVIDIA's to fix, because the function lives in
`isaac_ros_common/cmake` under the proprietary header.

## Notes on the check

`check.py` loads into a container named `pose_check_container`, not the default
`/ComponentManager`, and the environment sets `ROS_DOMAIN_ID=89`. Both matter: every
`component_container` on a DDS domain answers to `/ComponentManager`, and the other check
environments in this repo leave containers running. Addressing the default name sends load
requests to a prefix that does not have these packages installed, and the result —
`Could not find requested resource in ament index` — is indistinguishable from a real
registration bug and intermittent, since which container answers depends on discovery
order. That cost an hour; it is worth not repeating.

Six of the 21 components need constructor parameters (a tensor shape, an image size, a
score threshold below 1.0) and get plausible ones rather than being skipped — a component
that only loads unconfigured is a weaker result. The CV-CUDA nodes each reserve a ~369 MB
device memory pool by default and all 21 land in one container, so those get a 1 MB pool:
the point is that the CUDA allocation path works.
