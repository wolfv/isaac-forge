# isaac-forge

Packaging **Isaac ROS 4.5.0** (252 ROS 2 packages) on top of the **RoboStack** conda ecosystem,
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
| Target | Isaac ROS 4.5.0 · ROS 2 Jazzy · CUDA 13 · `linux-64` |
| RoboStack coverage | 133 of 149 external ROS deps already in `robostack-jazzy` (89%) |
| Chokepoint | VPI — sits under 218 of 252 packages |

**Done**

- Full dependency, license and blocker analysis of all 35 repos / 252 packages (`FINDINGS.md`).
- `recipes/vpi` — VPI 4.0.5 repacked from NVIDIA's Jetson apt repo. Builds clean, all tests pass
  including a real `find_package(vpi)` configure check. The shipped `libnvvpi.so.4.0.5` is verified
  byte-identical to NVIDIA's.

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

Repacking a vendor binary is the fallback, not the goal. Of the 45 packages:

| | count | |
|---|---|---|
| **source-built** | **32** | everything with published source |
| blob-only, irreducible | 8 | 7 `gxf_isaac_*` extensions + `isaac_ros_gxf` (prebuilt `.so` only) |
| no source anywhere | 2 | `vpi`, `nvv4l2` |
| external OSS, handled properly | 3 | `libcvcuda` + `libcvcuda-dev` from conda-forge, `magic_enum` from conda-forge |

**The backlog is done.** Every package with published source is now built from source;
the 10 remaining repacks are exactly the irreducible floor. `scripts/gen_source.py`
generates the source recipes, detecting per-package build traits (CUDA, Eigen, VPI,
rosidl, `ament_cmake_auto`) from each `CMakeLists.txt` rather than guessing.

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

**Next**

- Convert the remaining 31 repacks to source builds, starting with the NITROS core.
- **Audit the other 19 CUDA recipes for the same host-CUDA leak.** All of them already
  carry a `cuda-nvcc` host dep, which is why none of them produced a `_v2` symbol, but
  **none passes `${CMAKE_ARGS}`** and none uses `${{ compiler('cuda') }}`, so none gets
  the activation script's include-path ordering. They resolve the toolkit by a different
  route than the one that is actually guaranteed. Also fold `${CMAKE_ARGS}` into
  `scripts/gen_source.py`, which emits a bare `cmake -S . -B build` for every generated
  recipe.
- `nvblox` for a 3D reconstruction demo — not started.
- `tensorrt` (finish staged-recipes #29445 or repack `libnvinfer10`), then the DNN packages.
- Extend the generator over the remaining ~300 debs.

### TensorRT

Isaac needs `libnvinfer.so.10`; only 6 debs depend on it. conda-forge staged-recipes
[#29445](https://github.com/conda-forge/staged-recipes/pull/29445) (`carterbox`, still draft, CI
unstable, last touched 2026-05-27) is a 19-output `meta.yaml` targeting TensorRT **10.9.0.34** —
exactly the version NVIDIA's own `libnvinfer10` deb ships, so it is directly usable. It covers the
CUDA 11.8/12.8 tarballs only.

Note the oddity: `libnvinfer10` is `10.9.0.34-1+cuda12.8` while the rest of Isaac ROS 4.5 is CUDA
13 (`libnvinfer11` is the CUDA 13 build). Isaac links the CUDA 12.8 TensorRT anyway. For a repack
path the safest move is to repack NVIDIA's `libnvinfer10` deb directly, matching what Isaac was
built and tested against, rather than resolving the cross-major mixing ourselves.

## Architecture

Three layers, because only the middle one can be a normal RoboStack contribution.

**Layer 0 — vendored NVIDIA binaries** (`recipes/`, rattler-build).
`vpi`, `tensorrt`, `triton-server`, and the GXF extensions NVIDIA ships only as debs. These have no
ROS linkage, so repacking prebuilt binaries is sound.

`recipes/vpi` is hand-written and installs `libnvvpi.so` untouched (verified byte-identical), using
an activation script for the loader path. The generated repacks instead rewrite RUNPATHs to
`$ORIGIN`-relative at build time via `relink.py`, so they need no activation hook — see
`scripts/gen_repack.py`.

**Layer 1 — RoboStack gap fillers.**
The ~8 genuinely missing open-source ROS packages (`negotiated`, `hesai_ros_driver`,
`topic_based_ros2_control`, …). These belong upstream in RoboStack, not here.

**Layer 2 — the 252 Isaac ROS packages.** Either route works:

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

Source *is* published for all 252 ROS packages and for GXF core (395 `.cpp`, and 15 of its 16
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

```bash
# Clone the Isaac ROS sources (metadata only; add --full to build, --lfs for GXF/cuVSLAM blobs)
./scripts/clone.sh

# Regenerate the package inventory
pixi run inventory

# Generate repack recipes for a target and its Isaac-side closure
python scripts/gen_repack.py --closure demo/.cache/Packages \
    ros-jazzy-isaac-ros-visual-slam \
    --exclude ros-jazzy-isaac-ros-visual-slam \
    --exclude ros-jazzy-isaac-ros-image-proc     # these two are source-built

# Build everything
pixi run vpi          # just VPI (~420 MB package, ~1 GB unpacked)
pixi run layer0       # everything in recipes/

# Verify the built packages resolve in a clean environment
cd verify && pixi install && pixi run ros2 component types
```

## Layout

```
FINDINGS.md              measured analysis: scope, deps, blockers, licensing
ISSUES.md                upstream findings to raise with NVIDIA
external/staged-recipes/ recipes destined for conda-forge
packages.json            per-package inventory (generated)
pixi.toml                build/dev environment and tasks
recipes/                 Layer 0 rattler-build recipes
demo/                    runnable Isaac-ROS-on-RoboStack demo
scripts/clone.sh         clone the 35 upstream repos
scripts/inventory.py     regenerate packages.json
scripts/aptclosure.py    resolve deb dependency closures from the apt index
scripts/gen_repack.py    generate repack recipes from the apt index
scripts/overlay_debs.sh  overlay Isaac debs onto a conda prefix (demo shortcut)
scripts/fix_nvidia_driver.sh  Fedora driver fix (needs >= 580 for CUDA 13)
verify/                  clean-env check of the built packages
slam/                    cuVSLAM on the r2b Galileo dataset
bench/                   NVIDIA's benchmark harness (partially working)
src/                     cloned upstream sources (gitignored)
output/                  built packages (gitignored)
```
