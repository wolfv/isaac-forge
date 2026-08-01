# isaac-forge

Packaging **Isaac ROS 4.5.0** (253 source-visible ROS packages) on top of the **RoboStack** conda ecosystem,
using rattler-build recipes and pixi.

[`ISSUES.md`](ISSUES.md) collects the upstream findings worth raising with NVIDIA;
[`upstream/`](upstream/README.md) has three of them prepared as DCO-signed PR branches
on forks under `wolfv`.

Read [`FINDINGS.md`](FINDINGS.md) first — it records the measured dependency, platform and
licensing situation that determines the architecture below. `packages.json` is the
machine-readable per-package inventory.

## Where things stand

| | |
|---|---|
| Target | Isaac ROS 4.5.0 · ROS 2 Jazzy · CUDA 13 · `linux-64`; `linux-aarch64` in progress |
| RoboStack coverage | 133 of 149 external ROS deps already in `robostack-jazzy` (89%) |
| Chokepoint | VPI — sits under 218 of 252 packages (packaged; see `recipes/vpi`) |

**Done**

- Full dependency, license and blocker analysis of 36 repos / 253 source-visible packages (`FINDINGS.md`), including the separately documented `sensor_mounting_rig` repository.
- `recipes/vpi` — VPI 4.0.5 repacked from NVIDIA's apt repos. The amd64 build and tests pass,
  including a real `find_package(vpi)` configure check, and its `libnvvpi.so.4.0.5` is verified
  byte-identical to NVIDIA's. The ARM64 payload and checksum are now pinned for native Jetson
  validation.

- Verified that binary repacking composes with RoboStack (`FINDINGS.md` §5) — this is the
  cheap path, and it works.
- **A working demo with real GPU execution** — [`demo/`](demo/README.md). Overlays a 34-deb
  closure covering `image_proc`, `stereo_image_proc`, `depth_image_proc`, `visual_slam` and
  `apriltag` onto a RoboStack env: 30 ROS packages, 17 composable node components.

  Verified end-to-end on an RTX 4060 (driver 580.173.02, CUDA 13.0): a 640x480 image published
  from RoboStack `rclpy` comes back **resized to 320x240 by the GPU**, with real resampled pixel
  data. Five Isaac nodes run at once, including **cuVSLAM 15.0.0** (`cuvslam::WarmUpGPU()` in
  3.6 ms) and cuAprilTag. Only the two OpenCV-linked nodes are blocked.

  ```bash
  cd demo && ./setup.sh && pixi run check && pixi run e2e
  ```

- **25 real conda packages**, built and tested. `scripts/gen_repack.py` generates one repack
  recipe per Isaac deb from the apt index; two packages are source-built. Both soname gaps are
  closed, verified in a clean env resolved only from `output/` + robostack-jazzy + conda-forge:

  | | |
  |---|---|
  | repacked from NVIDIA debs | `$ORIGIN`-relinked, no activation hook |
  | `ros-jazzy-isaac-ros-visual-slam` | source-built, links `libboost_*.so.1.90.0` |
  | `ros-jazzy-isaac-ros-image-proc` | source-built, links `libopencv_*.so.413` |
  | `ros-jazzy-isaac-ros-h264-decoder` | source-built with the upstream patches, clean `DT_NEEDED` |

  All nine GPU components load into a single container — `ResizeNode`, `RectifyNode`,
  `ImageFormatConverterNode`, `ImageFlipNode`, `CropNode`, `PadNode`, `ImageNormalizeNode`,
  `AlphaBlendNode` and `VisualSlamNode` — cuVSLAM 15.0.0 warms up the GPU in ~6 ms, and
  **zero libraries resolve outside the prefix**. A 640x480 image pushed through `ResizeNode`
  comes back 320x240 with real resampled pixel data on the first frame. See `verify/`.

- **[`slam/`](slam/README.md) — cuVSLAM on NVIDIA's r2b Galileo dataset.** Tracked
  **6.04 m over 343 poses**, agreeing with the wheel odometry recorded in the same bag
  to **94.9%**. A node that loads proves packaging; a trajectory that matches ground
  reference proves the GPU maths is right.

  The full GPU path now runs: **NVDEC** hardware decode (`cuvid=1`) → CV-CUDA mono8
  conversion → cuVSLAM, with the decoders as the only image source. The CPU decode
  fallback (`USE_NVDEC=0`, `av`) still works and gives 6.06 m / 280 poses / 95.3% —
  fewer frames reach the tracker, which is the difference in the numbers.

- **[`manip/`](manip/README.md) — the manipulation stack, with cuMotion solving IK on the
  GPU.** **16 of the 18** packages in `isaac_ros_manipulation`, plus five cuMotion packages,
  `nvblox_msgs` and the interfaces they need — **28 new conda packages**. The whole set
  resolves into one environment from `output/` + robostack-jazzy + conda-forge, all 12 python
  modules import, `ros2 pkg list` sees 21 packages, and the C++ composable nodes dlopen —
  including NVIDIA's cuMotion planner, which parses the UR5e + Robotiq 2F-85 URDF/XRDF it
  ships, builds its collision model, and answers an action call:

  ```
  [cumotion_action_server]: IK succeeded with 26 solutions
  Goal finished with status: SUCCEEDED
  ```

  **26 IK solutions**, `planning_time` 17 ms at best (17–155 ms across runs, the spread being
  first-call GPU warm-up), from `libcumotion.so.1.1.0` as shipped — and the answer is
  *right*: `manip/fk_check.py` recomputes the pose from the returned joint angles with an
  independent numpy forward-kinematics implementation and lands **0.000 mm** from the
  requested gripper pose.

  ```bash
  cd manip && pixi run check && pixi run ik
  ```

  The stack is now complete: `isaac_ros_manipulation_asset_bringup` and
  `isaac_ros_manipulation_bringup` are packaged too. Their reference graph resolves across
  the whole DNN + nvblox stack. Both packaged inference backends, TensorRT and Triton, now
  resolve in the reference graph.

  Two open-source ROS packages had to be built to get here, and neither is NVIDIA's:
  `topic_based_ros2_control` (declared by both robot-description packages but **never
  released for jazzy** — humble only, `ISSUES.md` #15) and `robotiq_controllers` (released
  for jazzy, simply not selected in RoboStack; its sibling `robotiq_description` is there).
  The second belongs in RoboStack proper.

- **cuMotion works against Eigen 5, and that took a measurement to establish.** NVIDIA's
  `cumotionConfig.cmake` asks for `Eigen3 3.3`, which Eigen's own `SameMajorVersion` config
  rule turns into a hard rejection of the Eigen 5.0.1 that robostack-jazzy now builds
  against. Read literally it costs three packages — `isaac_ros_cumotion_moveit` needs
  `moveit_core`, `gear_assembly` needs the UR driver's controller chain, and
  `flexiv_driver_utils` needs the first.

  It is an over-constraint, not an ABI wall. The types that actually cross into
  `libcumotion.so` are `Eigen::Matrix<double,3,1,0,3,1>` and `Eigen::Quaternion<double,0>`
  passed by const reference — same template signature and same layout in both versions,
  which is why the symbols link at all. Compiled against Eigen 5.0.1 and linked against the
  Eigen 3 library as shipped, cuMotion returns the same 26 IK solutions and hits the target
  pose to 0.000 mm (the Eigen 3.4 build: 0.026 mm — a different valid branch of the 26).

  So we **patch the floor out** where it is written, in the `cumotionConfig.cmake` that
  `ros-jazzy-isaac-ros-nitros` installs, and assert the old text is there first so a future
  cuMotion fails loudly instead of silently skipping the patch. One `sed`, and it holds for
  every consumer. `ISSUES.md` #13 has the evidence and the upstream ask.

  Two things surfaced on the rebuild that this required, both pre-existing: GXF's prebuilt
  headers `#include "magic_enum.hpp"` by bare name, which stopped resolving when conda-forge's
  magic_enum moved its headers into a subdirectory in 0.9.7 (`ISSUES.md` #17), and our nitros
  recipe had `diagnostic_msgs` in `host` but not `run`, though nitros' exported ament
  dependencies make every consumer look for it.

- **`gen_source.py` now builds `ament_python` packages too**, which is what made the
  manipulation stack reachable: 12 of its 18 packages are setuptools projects, and the
  generator only knew how to run CMake. They install with `pip`, console scripts land in
  `bin/` to match RoboStack's own ament_python packages, and **run dependencies are read
  out of the module's imports rather than out of `package.xml`** — because these manifests
  are not reliable enough to resolve against (`ISSUES.md` #16: `isaac_ros_launch_utils`
  declares one dependency and imports five).

- **[`bench/`](bench/README.md) — NVIDIA's own benchmark harness, with numbers.**
  All 45 packages including `ros2_benchmark` + `isaac_ros_benchmark` build and install.
  The harness profiles the system, buffers the 2.9 GB `r2b_storage` dataset, negotiates
  NITROS formats and prints NVIDIA's metadata table reporting
  `Device OS : Linux 7.1.5-200.fc44.x86_64`.

  It now completes. `ResizeNode` RGB8 1920x1200 → 960x576 peaks at **2495 fps** over
  12476 frames with **0 missed**, mean frame-to-frame jitter 0.073 ms:

  | | |
  |---|---|
  | Peak throughput | 2495.5 fps (harness prediction: 2495.3) |
  | Frames sent / missed | 12476 / 0 |
  | Mean / max jitter | 0.073 ms / 2.17 ms |
  | Mean GPU utilization | 3.5% |

  This previously aborted in the measurement phase with an undiagnosed
  `std::runtime_error`. It was **not** diagnosed — it stopped reproducing across a
  Fedora 43→44 upgrade, an NVIDIA 580.173.02→610.43.03 driver upgrade and a package
  rebuild, and no attempt was made to attribute which one mattered. Worth knowing if it
  returns.

### Fixed: the source-built decoder was compiling against the host's CUDA 12

`ros-jazzy-isaac-ros-h264-decoder` used to fail to load standalone:

```
libdecoder_node.so: undefined symbol: cudaGetDeviceProperties_v2
```

CUDA 12's `cuda_runtime_api.h` aliases `cudaGetDeviceProperties` to
`cudaGetDeviceProperties_v2`; CUDA 13 dropped the alias and its `libcudart.so.13`
exports only the unversioned name. So a CUDA 12 header was reaching the compile even
though the recipe pins `cuda-version 13.*` and the build resolved `cuda-cudart-dev
13.3.29` — both of which were true and neither of which helped.

`-H` include tracing found it. The header was not a transitive include from VPI or
`nvbuf_utils`, which was the earlier guess. `decoder_node.hpp` includes plain
`<cuda_runtime.h>`, and that resolved to **`/usr/local/cuda/include/cuda_runtime.h` on
the build machine** — a Fedora-side CUDA 12.9 install (`CUDART_VERSION 12090`), whose
line 172 carries the alias. `-I/usr/local/cuda/include` was the *first* include flag on
the compile line, and conda's CUDA 13 headers live in
`$PREFIX/targets/x86_64-linux/include`, which was not on the include path at all.

The trigger is `find_package(CUDAToolkit REQUIRED)` in the decoder's `CMakeLists.txt`.
With no CUDA compiler in the build environment, CMake's `FindCUDAToolkit` falls through
to its `/usr/local/cuda` guess and silently adopts whatever the host machine has. **The
build was not hermetic**, and nothing about it looked wrong until a symbol failed to
resolve at `dlopen` time.

The fix is two lines and follows conda-forge:

- `${{ compiler('cuda') }}` in `build:`. Nothing here needs *compiling* by nvcc — this
  package has no `.cu` sources — but the compiler's activation script puts
  `$PREFIX/targets/<arch>/include` on `CXXFLAGS` and exports `CMAKE_ARGS`. Its own
  comment says it is there for "projects that don't enable the CUDA language but use
  FindCUDAToolkit", which is exactly this case.
- `build.sh` passes `${CMAKE_ARGS}` to `cmake`, which carries the
  `CMAKE_FIND_ROOT_PATH` that points `FindCUDAToolkit` at the prefix. No recipe in this
  repo was passing `CMAKE_ARGS` at all.

Two things worth knowing before copying this pattern:

- `recipes/*/variants.yaml` has to pin `cuda_compiler_version`. conda-forge's **global**
  pinning is still `12.9` — the exact release that carries the alias — so taking the
  default would reintroduce this bug. `13.0` matches conda-forge's in-flight
  `cuda130.yaml` migration.
- It also has to set `cuda_compiler: cuda-nvcc`. rattler-build's built-in default is
  `cuda`, which expands to `cuda_linux-64` and fails to resolve; conda-forge only avoids
  this because its pinning sets the same value.

`check_relocatable.sh` now asserts no `cuda*_v2` symbol is referenced, alongside the
existing absolute-`DT_NEEDED` check, because both failures are invisible at build time
and only appear when the node is `dlopen`ed.

With this fixed, **NVDEC hardware decoding works**: `DecoderNode` loads, reports
`V4L2 Decoder initialized, cuvid=1`, and decodes the r2b Galileo bag at 1920x1200 into
cuVSLAM — see [`slam/`](slam/README.md).

### Source-build where source exists

Repacking a vendor binary is the fallback, not the goal. Of the 210 recipes:

| | count | |
|---|---|---|
| **source-built** | **188** | 183 generated by `gen_source.py` + 5 hand-written (`isaac_ros_common`, `nitros`, `image_proc`, `visual_slam`, `h264_decoder`) |
| blob-only, irreducible | 17 | 16 `gxf_isaac_*` extensions + `isaac_ros_gxf` — `INTERFACE` targets that only `install()` a prebuilt `.so` |
| no source anywhere | 4 | `vpi`, `nvv4l2`, `tensorrt`, `isaac_ros_visual_mapping` (vendor binaries, no source published) |
| binary compat shim | 1 | `libabseil-debian3-compat` — Ubuntu's abseil, for its `debian3` symbol names |

210 recipes, and **188 of them compile from source.** Two of the 188 are not NVIDIA's:
`negotiated` and `topic_based_ros2_control`, neither of which has a jazzy release. Three
external OSS dependencies need no recipe at all — `libcvcuda`, `libcvcuda-dev` and
`magic_enum` all come from conda-forge.

**The backlog is done.** Every package with published source is now built from source;
the 10 remaining repacks are exactly the irreducible floor. `scripts/gen_source.py`
generates the source recipes, detecting per-package build traits (CUDA, Eigen, VPI,
rosidl, `ament_cmake_auto`) from each `CMakeLists.txt` rather than guessing, and handling
both `ament_cmake` and `ament_python` build types.

Both external OSS packages are off the repack list — see
[`external/staged-recipes/`](external/staged-recipes/README.md):

- **`libcvcuda`** now comes from **conda-forge** (0.16.0, `cuda130` build, plus
  `libcvcuda-dev` for headers). Safe despite Isaac being built against NVIDIA's 0.14:
  same soname, identical `NVCV_*` symbol version nodes, and every cvcuda/nvcv symbol
  the repacked binaries need resolves against it. No contribution needed.
- **`libv4l`** is source-built from a recipe written for conda-forge staged-recipes,
  replacing an Ubuntu deb repack. conda-forge has no v4l package at all today.

`h264_decoder` was the worst offender and is done: repacking it required rewriting
`DT_NEEDED` strings inside NVIDIA's `libdecoder_node.so`. That byte-patching phase has
been deleted from `scripts/gen_repack.py` — the decoder was the only package it ever
touched.

**`isaac_ros_nitros` is now source-built too**, which is the biggest single win since it
sits under everything. It has to be a hybrid, and the reason is worth knowing before
anyone tries a pure source build: the GitHub release tarball carries **git-lfs
pointers**, so `libcuvslam.so` arrives as 132 bytes of text. A naive source build would
install text files where libraries belong and break cuVSLAM, cuAprilTags and cuMotion at
runtime only. The recipe compiles `libisaac_ros_nitros.so` from source and fills each LFS
pointer in place from the official deb. Nothing is lost — cuVSLAM and cuMotion have no
published source and are in the irreducible floor regardless.

`isaac_ros_common` source-building also resolves `ISSUES.md` #5 by construction: built
from source it registers `${CMAKE_INSTALL_PREFIX}/share/isaac_ros_common/cmake` in the
ament index, so there is no `/opt/ros/jazzy` path to rewrite.

`scripts/gen_repack.py` has a `SOURCE_BUILT` set so regenerating recipes cannot silently
replace a source recipe with a repack.

- **[`pose/`](pose/README.md) — the pose-estimation stack, all five packages.** Every
  package in `isaac_ros_pose_estimation` builds from source, plus the two
  `isaac_ros_dnn_inference` packages they needed: **21 composable nodes, all loading into
  one container**, including `FoundationPoseNode` with its nvdiffrast CUDA rasteriser and
  the `SwitchMesh` service.

  ```bash
  cd pose && pixi run check
  ```

  `packages.json` marks four of the five blocked on `tensorrt` and centerpose on `triton`
  as well, and that is read off the manifests rather than the code. FoundationPose only
  ever had TensorRT as an `<exec_depend>`; what actually blocked it was
  `isaac_ros_dnn_image_encoder`, which lives in the TensorRT repo but does not itself
  touch TensorRT. And `isaac_ros_dope` and `isaac_ros_centerpose` do not either —
  `grep -r 'tensor_rt\|nvinfer\|triton'` over both `src/` and `include/` trees returns
  nothing. They are PnP decoders that read a `TensorList` off a topic. They declare the
  backends as `<depend>` instead of `<exec_depend>`, and
  `ament_auto_find_build_dependencies()` makes every `<depend>` a REQUIRED
  `find_package`, so an over-declaration was the entire blocker (`ISSUES.md` #18, two
  one-line patches, both prepared for upstream).

  What TensorRT still blocks is the **pipelines**, not the packages: FoundationPose needs
  an `isaac_ros_tensor_rt` node to serve its ONNX models and RT-DETR to supply detections,
  so unlike `slam/` this directory proves packaging rather than a working demo. It says so.

  Two findings worth carrying forward. The FoundationPose build is the first here to do
  CUDA **device linking** (`CUDA_SEPARABLE_COMPILATION` on nvdiffrast's rasteriser), and
  `nvlink` refused: nvcc was pinned to 13.0 while every recipe resolves `cuda-cudart-dev
  13.3.29`, so the toolkit had been three minors *older* than the runtime in all 20 CUDA
  recipes — invisible until something device-linked. `variants.yaml` now pins `13.3`, which
  **changes the build hash of every CUDA package here**. And `libcvcuda-dev` is pinned
  `>=0.16`, because FoundationPose is the first to call `find_package(nvcv_types)` and only
  conda-forge's 0.16 ships the CMake configs.

- **[`detect/`](detect/README.md) — the object-detection stack, all eight packages.**
  RT-DETR, Grounding DINO, YOLOv8 and DetectNet, plus their three NGC asset packages and
  `isaac_ros_grounding_dino_interfaces`. Six composable nodes, all loading.

  ```bash
  cd detect && pixi run check
  ```

  `packages.json` marks four of the eight `tensorrt`, and this time no patches were needed
  to disprove it: every package already declares its backend as `<exec_depend>` (DetectNet
  has Triton as a `<test_depend>` only), both of which are invisible to
  `ament_auto_find_build_dependencies()`. So the label was purely the
  manifest-reading artefact — which is now two repos in a row, and the reason the
  `tensorrt` blocker count in `packages.json` should not be trusted without checking
  whether the code includes a TensorRT header.

  Two findings here became generator rules rather than patch files, and both were worth
  more than the packages that prompted them:

  - **`install_isaac_ros_asset()`** downloads model weights from NGC and runs `trtexec` as
    part of the default build target, and dry-runs its script at configure time needing
    `$ISAAC_ROS_WS`. Four packages call it. Rewritten to register the ament resource
    without the download — an engine plan is specific to the GPU that built it, so this is
    a correctness fix, not a convenience (`ISSUES.md` #20).
  - **`find_package(Eigen3 3.3 REQUIRED NO_MODULE)`** appears verbatim in **18** packages.
    In config mode the version is a ceiling as well as a floor, so Eigen 5 rejects it, and
    `NO_MODULE` rules out the module-mode workaround. All 18 fail to configure against
    robostack-jazzy's Eigen 5. Version stripped, with an assertion in front so the rewrite
    cannot silently stop matching (`ISSUES.md` #13).

- **`isaac_ros_visual_mapping` — cuVGL and cuSFM, and it is deb-only.** `ISSUES.md` #22 used
  to say this package "does not exist", because the search was over the source trees and it
  has none. It is in the apt repository, NVIDIA's own page says it is "only released as a
  Debian package and is not available in source form", and it is now repacked:
  `recipes/ros-jazzy-isaac-ros-visual-mapping`, two outputs, 137 MB + 11 MB.

  **`export_extractor_engine` built a 5.2 MB FP16 TensorRT engine for sm_89 from the shipped
  ALIKED ONNX in 112 s** — NVIDIA's binary, running against conda-forge's gflags, glog 0.6,
  protobuf 3.21 and OpenCV 4.6 and this repo's TensorRT. 23 ELF files, **1107 library
  resolutions inside the prefix, zero unresolved**, nothing outside the prefix but glibc.

  Of 803 undefined symbols across the deb's 39 binaries, 52 do not resolve against
  conda-forge and 48 of those come from packages already here (cuVSLAM, CV-CUDA, CUDA 13,
  TensorRT). The remaining **four are abseil's, and they are the one genuine wall**: Debian
  renames abseil's inline namespace to `debian3`, so conda-forge's *identically versioned*
  abseil 20220623 defines `absl::lts_20220623::Status` where Isaac wants
  `absl::debian3::Status`. Same release, different mangled names — a soname alias resolves
  nothing, which was tried first. `recipes/libabseil-debian3-compat` repacks Ubuntu's build
  for those four symbols; the inline namespace is also what makes it co-installable with
  conda-forge's libabseil, so it is additive rather than a pin.

  glog and protobuf looked like the same problem and are not: pinned to what Ubuntu 24.04
  ships, conda-forge resolves **122 of 122** external glog and protobuf symbols (against
  glog 0.7 + protobuf 7.35 it resolves 50, so the pins are load-bearing).

  Two outputs, because one package could not coexist with its own consumers. The 38
  executables need `libopencv_*.so.406`; the four libraries are **static archives**, which
  have no `DT_NEEDED` and so impose no OpenCV at all. Of the 87 `cv::` symbols the archives
  need externally, 4.6 resolves 87 and 4.13 resolves **86** — the one holdout being
  `cv::cvtColor(InputArray, OutputArray, int, int)`, which grew a fifth `AlgorithmHint`
  parameter in OpenCV 4.10.

  What is still in the way of `isaac_ros_visual_global_localization`, and it is upstream's:
  `absl::Status` is the return type of nearly every function in eight of the public headers,
  so a consumer has to *compile* against a debian3 abseil; and the protobuf 3.21 pin
  collides with `cv_bridge`, whose OpenCV pulls protobuf 4.25. `ISSUES.md` #26 has the
  measurements and the asks. The base package does install beside `ros-jazzy-ros-core` and
  this repo's `isaac_ros_nitros`.

  Three upstream bugs fell out of running it, all in `ISSUES.md` #26: both CMake export sets
  bake `/usr/include/eigen3` and `/usr/include/opencv4` into `INTERFACE_INCLUDE_DIRECTORIES`
  on imported targets, which CMake rejects outright; the tools **segfault in their own error
  path** when an engine cannot be built; and `export_extractor_engine` writes into the model
  directory as well as `--output_model_dir`, so it fails on a read-only install.

- **82 more recipes in one pass — subsequently extended to 212 of the 253 inventoried packages**, up
  from about 120. Three commits, each a batch whose dependencies the one before it supplied:

  | | |
  |---|---|
  | `isaac_ros_cloud_control` | **all 13** — the VDA5050 fleet interface: message set, MQTT bridge, action handlers, mission client. Largest untouched repo, and nothing under it is proprietary — no GXF, no NITROS type adapter, no CUDA. |
  | `isaac_ros_image_segmentation` | **all 6** — U-Net, SegFormer, SegmentAnything 1 and 2 |
  | `isaac_ros_deploy` | **all 7**, and one of them completes `isaac_ros_cumotion` |
  | `isaac_ros_benchmark` | **25 of 29**, including the MoveIt benchmarks that pit cuMotion against OMPL |
  | `isaac_ros_dnn_stereo_depth` | **all 5** — ESS and FoundationStereo |
  | five more repos | apriltag, h264 encoder, teleop, data tools, jetson services, examples, unitree G1, SIPL camera |

  **`isaac_ros_cumotion` is complete.** `isaac_ros_cumotion_controllers` had been out of
  reach for exactly one dependency, `isaac_ros_inverse_dynamics` — which lives in
  `isaac_ros_deploy`, a repo nobody had opened.

  **`isaac_ros_apriltag` was the embarrassing one.** cuAprilTag has run in `demo/` since the
  first week, but only the *interfaces* package ever had a recipe; the node itself was
  reached through the deb overlay. Its whole closure had been built for weeks.

  **The inference-backend label in `packages.json` was wrong a third and fourth time.** All
  six `isaac_ros_image_segmentation` packages, and four of the seven `isaac_ros_deploy`
  packages, are marked `triton`. A grep for `nvinfer`, `tritonserver` or an
  `isaac_ros_triton` include across every `.cpp/.hpp/.cu/.h` in all ten returns **zero**
  hits: the manifests declare it `<exec_depend>` or `<test_depend>`, and
  `ament_auto_find_build_dependencies()` sees neither. After `pose/`, `detect/` and now
  these two, the rule is settled — ask whether the code includes a backend header, never
  whether the manifest names one.

  It is not always an artefact, and the distinction is the dependency *kind*. Four benchmark
  packages declare Triton as `<depend>`, which **does** become a REQUIRED `find_package`, so
  they fail at configure and no recipe-side change reaches them. Those four are left out.

  Three generator bugs, all found by validating against the channels rather than by a failed
  build — which is the only verification available while `output/` is being rebuilt:

  - **`libstatistics_collector` was being silently dropped.** The "system-looking key" test
    included `startswith("lib")`, and that is a core ROS 2 package `nvblox_ros` declares.
    rosdep separates the two cleanly: ROS keys use underscores, Debian keys use dashes.
  - **`tl_expected` was mapped to a conda-forge package that does not exist** under that name
    or any variant. It is `ros-jazzy-tl-expected` in robostack. `isaac_deploy_core` is the
    first package here to need it, which is why the wrong mapping sat unnoticed.
  - Five python import guesses that would have produced recipes that generate cleanly and
    then fail to solve: `boto3`, `paho`→`paho-mqtt`, `opentelemetry`→`opentelemetry-api`,
    `av`, `rosbags`.

  **`isaac_teleop_core` needed the missing-submodule fix for the third time in this release.**
  Its tarball carries an empty `isaac_teleop_core/IsaacTeleop/`, because that is a git
  submodule — after `nvblox_ros/nvblox_core` and the git-lfs pointers in `isaac_ros_nitros`.
  Credit where due: its CMakeLists says "Ensure the IsaacTeleop submodule is initialized",
  which is far better than nvblox's failure. `ISSUES.md` #27.

  **The remaining 41 are fully accounted for**: 23 are blocked by the tagging gap
  (`ISSUES.md` #23), 12 are ROS 1, 2 are `ISSUES.md` #26, and 4 have individual reasons:
  `isaac_ros_jetson_stats` (`jtop`), the ARM64-only `isaac_ros_sipl_camera`, and the two
  dataset/test packages `isaac_ros_r2b_galileo` and `nvblox_test`.

  **The Unitree G1 bridge is complete.** `ros-jazzy-unitree-api` builds the public BSD ROS
  interfaces from a pinned `unitreerobotics/unitree_ros2` commit; the Python bridge imports
  those generated messages and no native Unitree SDK is required.

**Next**

- **`libnvinfer_builder_resource.so` is only found via `LD_LIBRARY_PATH`.** Building the
  engine above needed `LD_LIBRARY_PATH=$PREFIX/lib`, because `libnvinfer.so.10` `dlopen`s the
  1.3 GB builder resource by bare name and `recipes/tensorrt` installs NVIDIA's binaries
  untouched (`binary_relocation: false`), so nothing points it at the prefix. `detect/` never
  saw this because the ament environment hook puts `$PREFIX/lib` on `LD_LIBRARY_PATH`; a
  non-ROS binary gets no such help. A `$ORIGIN` RUNPATH on `libnvinfer.so.10` would fix it
  for everyone, at the cost of rebuilding a 1.44 GB package.
- **An `absl::debian3` *dev* package, or a decision not to have one.** `libabseil-debian3-compat`
  ships no headers on purpose — a debian3 dev package must conflict with conda-forge's
  libabseil, and that trade is only worth making when someone builds
  `isaac_ros_visual_global_localization`. Until then that package is blocked on `ISSUES.md`
  #26(a), not on anything here.
- Convert the remaining repacks to source builds, starting with the NITROS core.
- **Rebuild the CUDA packages for `cuda_compiler_version: 13.3`** (see above). Nothing in
  `output/` is wrong, only differently named than a fresh build would produce — same
  situation as the python pin, and the same one-rebuild fix.
- **Audit the other 19 CUDA recipes for the same host-CUDA leak.** All of them already
  carry a `cuda-nvcc` host dep, which is why none of them produced a `_v2` symbol, but
  **none passes `${CMAKE_ARGS}`** and none uses `${{ compiler('cuda') }}`, so none gets
  the activation script's include-path ordering. They resolve the toolkit by a different
  route than the one that is actually guaranteed. Also fold `${CMAKE_ARGS}` into
  `scripts/gen_source.py`, which emits a bare `cmake -S . -B build` for every generated
  recipe.
- `nvblox` for a 3D reconstruction demo — not started. It is now also the thing standing
  between cuMotion and collision-aware planning: the planner's `read_esdf_world` path calls
  `/nvblox_node/get_esdf_and_gradient`, and `manip/ik.sh` has to turn it off. `nvblox_msgs`
  is already built.
- **Send `ISSUES.md` #13 upstream** — the cuMotion Eigen version request, with the patch and
  the IK/FK measurements. Nothing is blocked on it any more; it is a correctness question we
  would like NVIDIA to confirm rather than a wall.
- **`robotiq_controllers` is in robostack-jazzy now** (0.0.1, released 2026-07-30), so the
  duplicate recipe here is gone and `isaac_ros_manipulation_gear_assembly` resolves it from
  the channel. `rosidl_generator_dds_idl` and `vision_msgs_rviz_plugins` landed in the same
  release; both were on this repo's missing list, though neither freed a package on its own,
  because everything naming them also names a `nova_carter_*` package or a lidar driver that
  is still absent. `topic_based_ros2_control` cannot follow — rosdistro has no jazzy release
  of it at all (`ISSUES.md` #15), so it stays here.
- **Rebuild everything once for the new `python` variant pin.** `variants.yaml` now pins
  CPython 3.12 to match robostack-jazzy. The C++ packages already resolved to 3.12 through
  `rclpy`, so nothing is wrong in `output/` today, but the packages built before the pin
  carry different build hashes than a fresh build would.
- A cuMotion *trajectory* against ground reference, the way `slam/` does for cuVSLAM.
  `manip/fk_check.py` verifies an IK solution to 0.000 mm, which covers kinematics; it says
  nothing about whether a planned trajectory is smooth, collision-free or time-optimal.
- Validate the complete manipulation bringup graph on hardware. Both bringup packages now
  build, solve and pass their package tests; end-to-end execution still needs the robot,
  cameras and model assets selected by the launch configuration.
- **Build and test the 82 recipes added today.** They are generated and their dependencies
  are validated against the channels — every external dep exists and the whole set co-solves
  — but none has been compiled. `output/` was lost between sessions and is being rebuilt from
  scratch; that has to finish first. Note the rebuild runs with `--test skip`, so a separate
  test pass over every `.conda` is needed after it, the way `.github/workflows/release.yml`
  does it.
- **Make the `isaac-forge` prefix.dev channel readable.** Losing `output/` cost the whole
  local channel and there was no fallback, because the channel is private and its repodata
  returns 401 — so `--skip-existing all` cannot be used against it either. Publishing it
  read-only would make a lost `output/` a download rather than a rebuild, and would let CI
  skip work it has already done.
- Extend the generator over the remaining ~300 debs.

### TensorRT — done, in `recipes/tensorrt`

**Packaged.** TensorRT 10.13.3.9 repacked from NVIDIA's CUDA apt repository and
redistributed from this channel with NVIDIA's permission, which unblocks
`isaac_ros_tensor_rt` and with it every DNN pipeline in the stack. `detect/` proves it end
to end: `TensorRTNode` parses a generated ONNX graph, initialises the plugins, creates a
runtime and builds an engine.

Two decisions, both recorded in the recipe:

- **The debs, not the tarball** conda-forge staged-recipes#29445 builds from. That tarball
  is 6.18 GB and extracts to ~14 GB (`libnvinfer_static.a` alone is 3.6 GB), which does not
  fit a CI runner; the debs carry the same shared objects for 1.45 GB. This is the path this
  section already recommended, below.
- **10.13.3.9 + cuda13.0, not 10.9.0.34 + cuda12.8.** Mechanical rather than a preference: a
  cuda-12.8 TensorRT links `libcudart.so.12`, every package here requires
  `cuda-cudart >=13.3.29`, and conda-forge ships both CUDA majors under one package name, so
  such an environment does not solve at all. The TensorRT major is unchanged, so the soname
  Isaac looks for — `libnvinfer.so.10` — is too. The cost is that engine plans are not
  interchangeable with NVIDIA's own 10.9 debs.

The 1.3 GB `libnvinfer_builder_resource.so` is dlopen'd rather than linked, so no file list
or ELF check covers it; building a real engine in `detect/check.py` is what does.

**Triton is packaged.** `recipes/triton-server` builds the 2.60 C server API from public
source against the RoboStack-compatible protobuf/Abseil stack. `isaac_ros_triton` is patched
to consume its exported `TritonCore::triton-core-serverstub` target instead of downloading
the nonexistent public x86_64 tarball from NVIDIA's internal artifactory. The ROS component
dlopens cleanly; a C-API smoke test creates a GPU-enabled server and reports it live; and the
four formerly blocked Triton-dependent benchmarks now build and test. `ISSUES.md` #21 remains
an upstream distribution bug, but no longer blocks this channel.

#### The original analysis, for context

Isaac needs `libnvinfer.so.10`; only 6 debs depend on it. conda-forge staged-recipes
[#29445](https://github.com/conda-forge/staged-recipes/pull/29445) (`carterbox`, still draft, CI
unstable, last touched 2026-05-27) is a 19-output `meta.yaml` targeting TensorRT **10.9.0.34** —
exactly the version NVIDIA's own `libnvinfer10` deb ships, so it is directly usable. It covers the
CUDA 11.8/12.8 tarballs only.

Note the oddity: `libnvinfer10` is `10.9.0.34-1+cuda12.8` while the rest of Isaac ROS 4.5 is CUDA
13 (`libnvinfer11` is the CUDA 13 build). Isaac links the CUDA 12.8 TensorRT anyway. For a repack
path the safest move is to repack NVIDIA's `libnvinfer10` deb directly, matching what Isaac was
built and tested against, rather than resolving the cross-major mixing ourselves.

It blocks less than `packages.json` suggests. That inventory propagates a `tensorrt` blocker
to every package whose manifest names `isaac_ros_tensor_rt`, and a manifest naming it is not
the same as code calling it — `pose/` built all five pose-estimation packages without it, two
of them only needing a `<depend>` → `<exec_depend>` correction (`ISSUES.md` #18). The blocker
was real for `isaac_ros_tensor_rt` and `isaac_ros_triton` themselves, and for any *pipeline*
that has to actually run inference. It is worth re-testing rather than assuming for the rest
of the DNN packages: the question to ask each one is whether it includes a TensorRT header,
not whether it lists one.

## Jetson / ARM64 status

ARM64 enablement is in progress. The build workspace and build/test drivers understand
`linux-aarch64`, CUDA source builds select Jetson GPU architectures (`87;110;120`), and the VPI
recipe now selects NVIDIA's verified `arm64` VPI 4.0.5 debs and checksums. Build natively on a
Jetson running JetPack 7 / Ubuntu 24.04:

```bash
pixi install
pixi run arm64-render                 # quick recipe rendering audit
pixi run build -- --target linux-aarch64
pixi run test                         # tests intentionally require native execution
```

Native builds are the supported path for CUDA; an x86_64 `--target linux-aarch64` invocation is
useful for rendering and dependency audits, not end-to-end validation. The output goes to
`output/linux-aarch64/`, alongside architecture-independent packages in `output/noarch/`.
The release workflow also builds and tests on GitHub's native `ubuntu-24.04-arm` runner and uploads
passing ARM64 artifacts to the same `isaac-forge` prefix.dev channel.

The proprietary binary floor is now architecture-aware: VPI, TensorRT, the Debian-abseil ABI shim,
GXF core, all 16 GXF extensions, cuVSLAM, cuAprilTags and cuMotion select pinned ARM64 payloads.
The git-lfs objects are fetched from upstream's media endpoint and independently SHA256-pinned;
GitHub's 132-byte LFS pointer files are never packaged.

Two vendor-only packages still have no public JetPack 7 payload that can be built on a generic ARM
runner: `nvv4l2` (the libraries are part of the Jetson system image) and the closed
`isaac_ros_visual_mapping` tools. Their amd64 recipes remain explicitly skipped on ARM rather than
mislabeling x86 ELF files. The rest of the stack can build and publish while those optional branches
remain unavailable, and CI records any downstream packages they block.

To override the default GPU list for a particular Jetson, export `CUDA_ARCHITECTURES` before the
build (for example `CUDA_ARCHITECTURES=87` for an Orin-only build).

## Architecture

Three layers, because only the middle one can be a normal RoboStack contribution.

**Layer 0 — vendored NVIDIA binaries** (`recipes/`, rattler-build).
`vpi`, `tensorrt`, and the GXF extensions NVIDIA ships only as debs. These have no ROS
linkage, so repacking prebuilt binaries is sound. `triton-server` is built from public source.

`recipes/vpi` is hand-written and installs `libnvvpi.so` untouched (verified byte-identical), using
an activation script for the loader path. The generated repacks instead rewrite RUNPATHs to
`$ORIGIN`-relative at build time via `relink.py`, so they need no activation hook — see
`scripts/gen_repack.py`.

**Layer 1 — RoboStack gap fillers.**
The ~8 genuinely missing open-source ROS packages (`negotiated`, `hesai_ros_driver`,
`topic_based_ros2_control`, …). These belong upstream in RoboStack, not here.

**Layer 2 — the 253 source-visible Isaac ROS packages.** Either route works:

- **Repack the debs.** Cheapest, and gives the exact binaries NVIDIA tested. Verified to link
  cleanly against RoboStack: ROS 2 sonames are unversioned and match, and
  `libisaac_ros_nitros.so` resolves all 55 sonames with zero missing against
  `robostack-jazzy` + NVIDIA's repos + conda-forge `cuda-cudart`. Needs a `__glibc >=2.38`
  constraint and the OpenCV question below settled.
- **Build from source** with `pixi-build-ros` against `robostack-jazzy`. More work, but produces
  RoboStack-native builds that follow its CUDA/OpenCV pinnings and can be patched.

A sensible split: repack the proprietary foundation (unpatchable regardless) and source-build the
Apache-2.0 layer on top. See `FINDINGS.md` §5 for the measurements.

### A fully-from-source build is not achievable

Source *is* published for all 253 inventoried ROS packages and for GXF core (395 `.cpp`, and 15 of its 16
third-party deps have `if(X_DIR OR X_ROOT)` escape hatches so conda-forge can satisfy them without
patching). But there is a hard binary floor with no source anywhere:

- **15 of 18** `gxf_isaac_*` extensions in `isaac_ros_nitros` are `INTERFACE` targets that only
  `install()` a prebuilt `.so` (only `camera_utils`, `utils`, `gems` really build)
- **5 more** closed extensions exist as debs only: `tensorops`, `argus`, `rectify`, `sgm`, `hesai`
- cuVSLAM, cuMotion, VPI, TensorRT

These are load-bearing, not peripheral — `gxf_isaac_messages`, `gxf_helpers`, `atlas`, `optimizer`
and `message_compositor` are direct deps of `isaac_ros_nitros`; `tensorops`/`rectify` drive the
image pipeline; cuVSLAM *is* visual SLAM. So the question is only where to draw the line, and a
hybrid is mandatory. Details in `FINDINGS.md` §5b.

### Both soname gaps: solved by source-building two packages

OpenCV and Boost were the only genuine incompatibilities, and the same fix handled both.

| Gap | NVIDIA's deb wants | RoboStack has | Fix |
|---|---|---|---|
| OpenCV | `libopencv_*.so.406` (4.6) | 4.13 (pinned by `cv_bridge`) | source-build `isaac_ros_image_proc` |
| Boost | `libboost_*.so.1.83.0` | 1.90 | source-build `isaac_ros_visual_slam` |

Source-building beat a `.406`/`1.83` compat package: both packages are Apache-2.0 with real
source, OpenCV feeds exactly one target (`rectify_node`) and cuVSLAM enters as a prebuilt imported
`.so`, so neither rebuild touches NVIDIA's accelerated code. A compat package would instead have
put two OpenCVs sharing the `cv::` namespace into one address space.

Note the pin that matters: `libopencv 4.13.*`, matching RoboStack's `cv_bridge`. Building against
conda-forge's default 5.0 resolves fine in isolation but reintroduces the two-OpenCV hazard as soon
as `cv_bridge` is in the same process.

## Licensing

181 packages are Apache-2.0; 69 are proprietary, and the proprietary ones are the foundation
(`isaac_ros_common`, `isaac_ros_nitros`, `isaac_ros_gxf`, all 21 nitros type adapters).
`FINDINGS.md` §4 records the terms and which packages fall where, so the split is documented if it
ever matters.

Three packages have a bare copyright block in `<license>` instead of a license name — worth
reporting upstream as a packaging bug.

## Usage

Every build recipe is checked in as `recipes/<package>/recipe.yaml` and is ready for
`rattler-build`; neither local builds nor CI generate recipes first. The scripts named
`gen_*` are maintainer tools for adding or refreshing recipes, not part of the build path.
A fresh clone is therefore enough to run `pixi run build`.

```bash
# Optional maintainer workflow: clone sources and refresh inventory/recipes.
# This is not required to build the checked-in YAML recipes.
# Clone the Isaac ROS sources (metadata only; add --full to build, --lfs for GXF/cuVSLAM blobs)
./scripts/clone.sh

# Regenerate the package inventory
pixi run inventory

# Generate repack recipes for a target and its Isaac-side closure
python scripts/gen_repack.py --closure demo/.cache/Packages \
    ros-jazzy-isaac-ros-visual-slam \
    --exclude ros-jazzy-isaac-ros-visual-slam \
    --exclude ros-jazzy-isaac-ros-image-proc     # these two are source-built

# Build everything into ./output, which is the channel the recipes resolve against.
# Resumable: `build` skips whatever is already there, so an interrupted run continues.
pixi run build                        # every recipe (add -- --fresh to start over)
pixi run test                         # every package's own tests, once the set is complete
pixi run vpi                          # just VPI (~420 MB package, ~1 GB unpacked)
pixi run prune                        # drop build trees, keep the packages

# Verify the built packages resolve in a clean environment
cd verify && pixi install && pixi run ros2 component types
```

`build` skips tests and `test` runs them afterwards, on purpose: a package's tests resolve
its own run dependencies in a fresh environment, and early in a from-scratch build those
siblings are not in `output/` yet. Deferring them means build order only has to satisfy
compilers, not test environments.

`output/` is gitignored and holds both the packages (~6 GB) and rattler-build's per-package
work trees (~55 GB across the full set). `build` prunes each work tree as its package lands;
`prune` clears whatever is left.

## Layout

```
FINDINGS.md              measured analysis: scope, deps, blockers, licensing
ISSUES.md                upstream findings to raise with NVIDIA
external/staged-recipes/ recipes destined for conda-forge
packages.json            per-package inventory (generated)
pixi.toml                build/dev environment and tasks
recipes/                 Layer 0 rattler-build recipes
demo/                    runnable Isaac-ROS-on-RoboStack demo
scripts/build_all.sh     rebuild every recipe into output/ (resumable, prunes as it goes)
scripts/test_all.sh      run every built package's own tests against the finished channel
scripts/clone.sh         clone the 36 upstream repos
scripts/fetch_sources.sh populate .srccache/ with the tarballs gen_source.py inspects
scripts/inventory.py     regenerate packages.json
scripts/aptclosure.py    resolve deb dependency closures from the apt index
scripts/gen_source.py    generate source-build recipes from .srccache
scripts/gen_repack.py    generate repack recipes from the apt index
scripts/overlay_debs.sh  overlay Isaac debs onto a conda prefix (demo shortcut)
scripts/fix_nvidia_driver.sh  Fedora driver fix (needs >= 580 for CUDA 13)
verify/                  clean-env check of the built packages
slam/                    cuVSLAM on the r2b Galileo dataset
manip/                   the manipulation stack, cuMotion solving IK
pose/                    the pose-estimation stack, 21 components loading
detect/                  the object-detection stack, 6 components loading
yolo/                    real YOLOv8 TensorRT inference with image/video Rerun visualization
bench/                   NVIDIA's benchmark harness (partially working)
src/                     cloned upstream sources (gitignored)
output/                  built packages (gitignored)
```
