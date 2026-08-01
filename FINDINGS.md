# isaac-forge — feasibility analysis

Packaging **Isaac ROS 4.5.0** on top of the **RoboStack** conda ecosystem.
All figures below were measured from the upstream sources, the NVIDIA apt repos and the
conda channel repodata on 2026-07-27. Machine-readable inventory: `packages.json`.

## 1. Scope

| | |
|---|---|
| Inventoried repos (`NVIDIA-ISAAC-ROS/isaac_ros_*`, `gxf`, `ros2_benchmark`, `sensor_mounting_rig`) | 36 |
| Source-visible packages (distinct `package.xml` names) | **253** |
| Upstream release | 4.5.0 (coordinated push 2026-07-07) |
| Target ROS distro | **Jazzy** |
| Reference platform | Ubuntu 24.04 / CUDA **13.0** / driver 580+ / Ampere or newer |
| Jetson reference | JetPack 7.1 on Jetson Thor |
| Upstream distribution | apt debs, `https://isaac.download.nvidia.com/isaac-ros/release-4 noble main` (public, no auth) |

12 distinct inventoried names are ROS 1 packages (`isaac_ros_noetic_interfaces` and the ROS 1 bridge) — out of scope for a Jazzy stack. The source tree has one additional ROS 1 `nvblox_msgs`, but the inventory deliberately keeps the ROS 2 package with the same name.

## 2. RoboStack fit: very good

Of 149 distinct external **ROS** dependencies, **133 (89%) already exist in `robostack-jazzy`**
(910 `ros-jazzy-*` packages in that channel).

The 16-package gap, and what each actually needs:

| Dependency | Resolution |
|---|---|
| `negotiated` (4 pkgs) | build — small open-source ROS pkg |
| `hesai_ros_driver` (3) | build — open source |
| `topic_based_ros2_control` (2) | build — open source |
| `sllidar_ros2`, `vision_msgs_rviz_plugins`, `robotiq_controllers`, `unitree_api`, `rosidl_generator_dds_idl` | build — open source |
| `nova_carter_*`, `nova_developer_kit_description` | build — from `nova_carter` / `nova_developer_kit` repos |
| `cvcuda0-dev` | **map** → conda-forge `libcvcuda` 0.16.0 |
| `isaac-ros-cli`, `isaac_ros_bi3d_interfaces`, `isaac_ros_visual_mapping` | Isaac-internal, come along with the build |
| `ament_python` | rosdep alias, maps to existing tooling |

The CUDA-side stack is **already fully covered by conda-forge**:
`cuda-toolkit` 13.3.1, `cuda-version` 13.3, `cudnn` 9.25, `libcvcuda` 0.16.0, `pytorch` 2.13,
`onnx` 1.22, `onnxscript` 0.7.1, `cuda-python` 13.3.1, `cupy` 14.1, `transformers`, `trimesh`, `warp-lang`.

Upstream's `python3-*-pip-shim` debs are thin pip wrappers; each maps to a real conda-forge package.

## 3. Non-conda NVIDIA binaries — all publicly obtainable

None of these exist in any conda channel today. All are downloadable without authentication.

| Component | Source | Blocks |
|---|---|---|
| **VPI 4.0.5** (`libnvvpi4`, `vpi4-dev`, `python3.12-vpi4`) | `https://repo.download.nvidia.com/jetson/x86_64/noble r38.4 main` | **218 / 252** |
| **TensorRT** (`libnvinfer*`) | CUDA apt repo `ubuntu2404/x86_64` | 37 |
| **triton-server** 2.62 | Isaac ROS apt repo | 27 |
| 5 closed GXF extensions (`tensorops`, `argus`, `rectify`, `sgm`, `hesai`) | Isaac ROS apt repo (`ros-jazzy-gxf-isaac-*`) | 9 |
| **GXF core** (56 `.so`, CUDA 13.0, x86_64 + aarch64) | prebuilt, committed in `isaac_ros_nitros/isaac_ros_gxf` | all |
| **cuVSLAM** (`libcuvslam.so`) | prebuilt, committed in `isaac_ros_nitros/lib/cuvslam` | visual_slam |

**VPI is the single chokepoint.** It enters through only four packages — `isaac_ros_common`,
`isaac_ros_nitros`, `isaac_ros_nitros_image_type`, `isaac_ros_vpi_utils` — and `isaac_ros_common`
sits under almost everything. One `vpi` conda package unblocks 218 of 252.

Blocker reach (transitive): `vpi` 218 · `needs_new_ros_pkg` 129 · `tensorrt` 37 · `ros1` 31 ·
`triton` 27 · `closed_gxf` 9 · no blockers at all 18.

## 4. Licensing — the real constraint

Declared `<license>` across the 252 packages:

- **181 Apache-2.0**, 2 MIT
- **69 non-open**, broken down as:
  - 65 `NVIDIA Isaac ROS Software License`
  - 1 `"NVIDIA Isaac ROS Software License"` — stray quotes, same license
  - 3 with **no license name at all**: the `<license>` tag contains a bare copyright block ending
    "*Any use, reproduction, disclosure or distribution of this software and related documentation
    without an express license agreement from NVIDIA CORPORATION is strictly prohibited*".
    These are `isaac_ros_mcap_lerobot_converter` and two others — strictly speaking they carry **no
    distribution grant whatsoever**, not even the §1c binary grant. Worth reporting upstream as a
    packaging bug; assume "no redistribution" until clarified.

The 69 proprietary packages are not leaves. They are the **foundation**: `isaac_ros_common`,
`isaac_ros_gxf`, `isaac_ros_nitros`, `isaac_ros_managed_nitros`, `isaac_ros_pynitros` and all 21
`isaac_ros_nitros_*_type` adapters. Everything else depends on them. Notably the 18
`gxf_isaac_*` extensions in the same repo **are** Apache-2.0 — but they build against the
proprietary GXF core.

Relevant terms of the NVIDIA Isaac ROS Software License:

- **§1c** — may distribute the software "(i) as incorporated into a software application that has
  material additional functionality … or (ii) **unmodified in binary format**".
- **§2b** — must distribute "subject to terms at least as protective as the terms of this license".
- **§4c** — outside §1, "may not … modify, or create derivative works of any portion".
- **§4f** — "may not use the SOFTWARE in any manner that would cause it to become subject to an
  open source software license" — including terms requiring redistribution at no charge.
- **§4a** — licensed to develop applications "only for their use in systems with NVIDIA GPUs".
- **§3** — may let employees/contractors use it "from your secure network"; academic institutions
  likewise.

Consequences:

1. Publishing built binaries of the proprietary 65 to conda-forge, or to an unrestricted public
   channel, is **not defensible** under §2b + §4f.
2. An **organisation-internal channel** is explicitly contemplated by §3.
3. **Source builds on the end user's machine** are clean — the user obtains the software from
   NVIDIA and accepts the license themselves; nothing is redistributed.
4. Patching proprietary sources is a §4c problem. Build-system-only fixes should be pushed
   upstream rather than carried as patches, wherever feasible.
5. The Apache-2.0 subset is freely redistributable, but is not independently *useful* — it needs
   the proprietary NITROS/GXF layer underneath.

## 5. Deb-repacking against RoboStack: measured to work

An earlier revision of this document claimed repacking the Isaac debs could not compose with
RoboStack, inferring ABI incompatibility from the debs' `Depends:` field. **That was wrong** —
`Depends:` is apt packaging metadata and says nothing about ELF ABI. Measured directly, the Isaac
binaries link cleanly against RoboStack.

### ROS sonames are unversioned and match exactly

`libisaac_ros_nitros.so` NEEDs:

```
libament_index_cpp.so   librclcpp.so   librcl.so   librcutils.so
librmw.so   libtracetools.so   libdiagnostic_msgs__rosidl_typesupport_cpp.so
```

ROS 2 sets no `SOVERSION`, so these are unversioned — and RoboStack's `librclcpp.so` reports
`SONAME: librclcpp.so`, identical. Every one of the seven resolves in a RoboStack env.

### Symbols resolve, not just sonames

Of the 353 undefined symbols in `libisaac_ros_nitros.so`, 141 are ROS-related. Against
`robostack-jazzy` (`rclcpp` 28.1.18, `rcutils` 6.7.5, `rmw` 7.3.3, `ament_index_cpp` 1.8.4),
**139 of 141 resolve**. The two that did not were `negotiated::NegotiatedPublisher` and
`negotiated::NegotiatedSubscription` — not an ABI mismatch, just a package RoboStack lacks. NVIDIA
ships `ros-jazzy-negotiated` and `ros-jazzy-negotiated-interfaces` in its own apt repo.

### Full loader test: zero unresolved

With the RoboStack env + the Isaac debs + conda-forge `cuda-cudart 13.*`:

```
ldd libisaac_ros_nitros.so  ->  55 sonames resolved, 0 not found
```

### ABI floor

`libisaac_ros_nitros.so` requires `GLIBC_2.38` and `GLIBCXX_3.4.32`. Express as a
`__glibc >=2.38` run constraint (Ubuntu 24.04+, Fedora 39+); conda-forge's `libstdcxx` 15.2
provides well past `GLIBCXX_3.4.32`.

### Genuine mismatches: OpenCV and Boost

18 of the 392 debs link Ubuntu noble's OpenCV 4.6 (`libopencv_core.so.406t64` and friends).
conda-forge is at OpenCV **5.0**, so those sonames do not exist. Options:

1. Repack Ubuntu's `libopencv-*406t64` runtime debs as a compat package providing only the `.406`
   sonames. Isolated, and does not disturb conda's OpenCV.
2. Build just those ~18 packages from source against conda's OpenCV.

Option 1 carries a caveat: if any single process loads both OpenCV 4.6 and conda's OpenCV 5.0
(e.g. an Isaac node alongside RoboStack's `cv_bridge`), the two share the `cv::` namespace and
symbol interposition becomes a real hazard. Spot-checking found `librectify_node.so` links OpenCV
but *not* `cv_bridge`, so the two may not actually co-occur — this needs a per-package check across
all 18 before committing to option 1.

**Boost** is the same shape, found while extending the demo: `libvisual_slam_node.so` needs
`libboost_thread.so.1.83.0` / `libboost_chrono.so.1.83.0` (Ubuntu noble), while the RoboStack env
resolves Boost **1.90**. Pinning `libboost = "1.83.*"` fails to solve, because RoboStack's
`ros2-distro-mutex` constrains `libboost 1.84.*`.

Watch for host leakage when testing this: on Fedora 43 the node *appears* to link, because
`/lib64/libboost_thread.so.1.83.0` exists on the host and the loader finds it. `demo/check.py`
explicitly fails any resolution outside `$CONDA_PREFIX` for exactly this reason.

Here source-building is the better answer than a compat package: `isaac_ros_visual_slam` is
Apache-2.0 with real source (10 `.cpp`) and takes cuVSLAM in as an imported `.so`, so rebuilding
just that wrapper against RoboStack's Boost removes the mismatch entirely. This is the clearest
concrete case for the hybrid split in §6.

### Everything NVIDIA-side is self-contained

GXF core, the closed `gxf_isaac_*` extensions, cuVSLAM, cuMotion, `negotiated`, `libcvcuda0`,
`triton-server` are all in NVIDIA's own public repos, and VPI in the Jetson repo. So the ROS
interface surface to RoboStack is small and well defined: `rclcpp`, `rcl`, `rcutils`, `rmw`,
`tracetools`, `ament_index_cpp`, and the `rosidl` typesupport / message libraries.

### Consequence

Binary repacking is viable and dramatically cheaper than 252 source builds. It also gets exactly
the binaries NVIDIA tested. The trade-off is that you inherit their toolchain and CUDA/OpenCV
pinnings rather than RoboStack's, and cannot patch anything.

## 5b. Is a from-source build possible? Partly — there is a hard binary floor

Measured from the git indexes (not the sparse checkouts), so this counts what upstream actually
publishes.

### Source is available and buildable

- **All 252 ROS packages' own code.** Real source, standard `ament_cmake` / `ament_python`.
  `isaac_ros_nitros` itself has 84 `.cpp` and builds via
  `ament_auto_add_library(isaac_ros_nitros SHARED src/nitros_node.cpp …)`. Repo `.cpp` counts:
  `gxf` 395, `isaac_ros_nitros` 84, `isaac_ros_deploy` 59, `isaac_ros_nvblox` 37,
  `isaac_ros_image_pipeline` 29, `isaac_ros_pose_estimation` 27, etc.
- **GXF core is buildable.** The `gxf` repo carries the real thing (395 `.cpp`, top-level
  `CMakeLists.txt`). Its `Superbuild.cmake` pulls third-party deps via `ExternalProject`, and
  several of those URLs point at `urm.nvidia.com`, which **has no public DNS record** — so the
  default fetch path is unusable outside NVIDIA. But 15 of the 16 third-party modules are guarded:

  ```cmake
  if(yaml-cpp_DIR OR yaml-cpp_ROOT)
      find_package(yaml-cpp REQUIRED)
  else()
      ExternalProject_Add(...)   # urm.nvidia.com
  endif()
  ```

  Passing `-D<dep>_ROOT=$PREFIX` switches each to `find_package`, so conda-forge can satisfy them
  **with no patching**. The 16th, `Boost`, calls `find_package(Boost 1.74.0 REQUIRED)`
  unconditionally, which is already what we want.

  conda-forge has: `boost` 1.85, `dlpack` 1.3, `gflags` 2.3.1, `gtest` 1.17, `magic_enum` 0.9.8,
  `nlohmann_json` 3.12, `protobuf`, `pybind11` 3.0.3, `rmm`, `ucx` 1.21, `yaml-cpp` 0.8.0.
  Still to sort: `gRPC` (conda-forge names it `libgrpc`/`grpc-cpp`), `cpprestsdk`, `breakpad` +
  `lss` (crash handler — check for a CMake option to disable), and `nvsci` (Tegra-only, not needed
  on x86_64).

### Binary-only, with no source published anywhere

| Component | Count | Form |
|---|---|---|
| `gxf_isaac_*` extensions inside `isaac_ros_nitros` | **15 of 18** | `add_library(… INTERFACE)` that only `install()`s a prebuilt `.so` |
| Closed `gxf_isaac_*` extensions absent from every repo | **5** | `tensorops`, `argus`, `rectify`, `sgm`, `hesai` — deb only |
| cuVSLAM | 1 | `libcuvslam.so` (git-lfs blob) |
| cuMotion | 1 | `libcumotion.so.1.1.0` (git-lfs blob) |
| VPI, TensorRT | 2 | proprietary, no source |
| triton-server | 1 | open source upstream, shipped prebuilt |

Only 3 of the 18 in-repo extensions genuinely build: `gxf_isaac_camera_utils` and
`gxf_isaac_utils` (both `SHARED` with sources) and `gxf_isaac_gems` (header-only).

### Conclusion: a 100% from-source stack is not achievable

The binary-only set is **not optional and not peripheral**. `gxf_isaac_messages`,
`gxf_isaac_gxf_helpers`, `gxf_isaac_atlas`, `gxf_isaac_optimizer` and
`gxf_isaac_message_compositor` are direct dependencies of `isaac_ros_nitros` itself; `tensorops`
and `rectify` are required by the image pipeline; cuVSLAM is the entirety of visual SLAM. There is
no configuration in which Isaac ROS runs without prebuilt NVIDIA GXF extensions.

So the realistic choice is not "source vs binary" but **where to draw the line**:

- Binary floor (unavoidable): ~20 GXF extensions, cuVSLAM, cuMotion, GXF core if you prefer the
  shipped build, VPI, TensorRT.
- Optional source layer: the 252 ROS packages and GXF core — buildable against RoboStack if you
  want RoboStack-native builds, patchability, and its CUDA/OpenCV pinnings.

Worth raising with NVIDIA: the 15 blob-only extensions **declare `Apache-2.0`** in their
`package.xml` while shipping no source. Apache-2.0 does not oblige anyone to publish source, so
this is not a licence violation — but it is surprising, and if the source were released those 15
would become buildable.

## 6. Recommended architecture

A hybrid, in three layers:

**Layer 0 — vendored NVIDIA binaries (rattler-build recipes, repack from debs/git).**
`vpi`, `tensorrt`, `triton-server`, `isaac-ros-gxf` (GXF core), `cuvslam`, and the 5 closed
`gxf_isaac_*` extensions. No ROS linkage, so binary repacking is sound. Unblocks everything.

**Layer 1 — RoboStack gap fillers (`pixi-build-ros` or standard RoboStack recipes).**
The ~8 genuinely missing open-source ROS packages (`negotiated`, `hesai_ros_driver`,
`topic_based_ros2_control`, …). These belong upstream in RoboStack, not here.

**Layer 2 — the 252 Isaac ROS packages.** Two routes, and §5 shows both are open:

- *Repack the debs* — cheapest, and gives the exact binaries NVIDIA tested. Measured to link
  cleanly against RoboStack. Needs the OpenCV 4.6 question settled and a `__glibc >=2.38`
  constraint.
- *Build from source* with `pixi-build-ros` against `robostack-jazzy` — more work, but yields
  RoboStack-native builds that follow its CUDA/OpenCV pinnings and can be patched.
  `pixi-build-ros` already reads `package.xml`, maps deps via RoboStack's `robostack.yaml`, and
  supports `extra-package-mappings`, which is where the Layer 0 names get wired in
  (`libnvvpi4` → `vpi`, `cvcuda0-dev` → `libcvcuda`, the `-pip-shim`s → conda-forge).

A sensible split: repack the proprietary foundation (which cannot be patched anyway) and
source-build the Apache-2.0 layer on top, where RoboStack-native builds have real value.

**Distribution** then splits by license: Apache-2.0 packages may go to a public channel; the
proprietary 69 either stay source-only (each user builds locally) or go to an
organisation-internal channel under §3.

### Layer 0 is not publicly redistributable either

Worth stating plainly, because it was not obvious before reading the EULAs: the Layer 0 vendored
binaries cannot go on a public channel any more than the Isaac ROS packages can. The VPI EULA
(bundled in the `libnvvpi4` deb) grants distribution of "any portion of the SDK" — but only
"as incorporated in object code format into a **software application**", requiring that the
application have "material additional functionality beyond the included portions of the SDK"
(§1.2(i)) and that the distributable portions "**only be accessed by your application**" (§1.2(ii)).

A standalone `vpi` conda package is not an application and is accessible to anything that installs
it, so it satisfies neither condition. TensorRT's terms are structured the same way — which is
presumably why TensorRT has never appeared on conda-forge.

The practical consequence: **the recipes are the publishable artifact, not the packages they
produce.** Each recipe fetches from NVIDIA's own servers at build time, so a user running
`pixi run layer0` is exercising their own "install and use" grant and nothing is redistributed by
us. Organisations can additionally host the built packages internally under §3 / §1.3.

## 7. Notes on the vendored blobs

The GXF core and cuVSLAM binaries committed to `isaac_ros_nitros` are **git-lfs pointers**, e.g.

```
version https://git-lfs.github.com/spec/v1
oid sha256:c52966813180fbfa6ed676982f9b600d3e270635fe2b838cfba1d7e26c0d3c7a
size 2721408
```

Platform variants present: GXF core `gxf_{x86_64,aarch64}_cuda_13_0`; cuVSLAM
`lib_x86_64_cuda_{12_6,13_0}` and `lib_aarch64_jetpack{61,70}`. Both have the CUDA 13.0 x86_64
build needed for 4.5.0.

For Layer 0 recipes, sourcing these from the **debs** (`ros-jazzy-isaac-ros-gxf`) is preferable to
git-lfs: a plain URL source with a `sha256` is reproducible and avoids an lfs dependency in the
build environment.

## 8. Open questions

- Whether upstream will accept build-system patches, to avoid carrying §4c-problematic diffs.
- Jetson/`linux-aarch64`: GXF and cuVSLAM ship aarch64 blobs, and VPI aarch64 comes from the
  Jetson `arm64` repo, but RoboStack's own aarch64 coverage needs a separate check.
- Whether `find_package(vpi REQUIRED)` in `isaac_ros_nitros` can be satisfied by a repacked VPI
  (it ships a CMake config); needs a real build to confirm.
