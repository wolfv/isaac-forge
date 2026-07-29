# Isaac ROS 4.5.0 — portability findings

Collected while packaging all 252 Isaac ROS packages as conda packages and running
them on **Fedora** (glibc 2.42, GCC 15) against RoboStack's ROS 2 Jazzy, with no
container and no Ubuntu.

Context worth stating up front: **the stack ports remarkably well.** NITROS, GXF,
cuVSLAM, cuAprilTag, CV-CUDA and VPI all relocate cleanly, ROS 2 sonames match
RoboStack's exactly, and 139 of the 141 ROS symbols in `libisaac_ros_nitros.so`
resolve against RoboStack's `rclcpp` without modification. cuVSLAM tracked 6.05 m on
the r2b Galileo dataset and agreed with the bag's wheel odometry to 95.2%.

Everything below is a small, contained fix. Ordered by how much it blocks.

## Can we fix these ourselves?

Mostly yes. Five of the six actionable items live in public, permissively licensed code,
and Isaac ROS `CONTRIBUTING.md` accepts contributions under Apache-2.0 with DCO
sign-off. We are happy to send the PRs.

| # | Issue | Where the fix lives | License | Who can patch |
|---|---|---|---|---|
| 1 | `cuvslam2.h` missing `<cstdint>` | `isaac_ros_nitros/lib/cuvslam/include/` | **NVIDIA Open Software License** — grants modification | **us, via PR** |
| 2 | Absolute `DT_NEEDED` in the H.264 decoder | `isaac_ros_h264_decoder/CMakeLists.txt:42-44` | **Apache-2.0** | **us, via PR** (proper fix is NVIDIA's — see below) |
| 3 | `urm.nvidia.com` unreachable | `gxf/com_nvidia_gxf/third_party/cmake/*.cmake` | **Apache-2.0** | **us, via PR** |
| 4a | Stray quotes in a `<license>` tag | `isaac_ros_nova/isaac_ros_data_validation` | metadata in a public repo | **us, via PR** |
| 4b | Copyright block instead of a license name (×3) | `isaac_ros_nova`, `isaac_ros_manipulation` | ambiguous — see below | **NVIDIA to confirm intent** |
| 5 | Absolute `/opt/ros/jazzy` in the ament index | `isaac_ros_common` | NVIDIA Isaac ROS Software License (no modification) | **NVIDIA only** |
| 6 | `negotiated` deb uses a multiarch subdir | your deb build config | n/a | **NVIDIA** (not an upstream bug — see below) |
| 9 | `launch_testing` pytest 8 hook signature | `ros2/launch` (jazzy branch) | **Apache-2.0** (not NVIDIA's) | **us — PR prepared, backport from rolling** |
| 11 | Every `v4.x` GXF tag points at 3.2-era source | `NVIDIA-ISAAC-ROS/gxf` tags | n/a — tagging, then a source release | **NVIDIA only** |
| 12 | `isaac_ros_common` uses CMake's removed `FindCUDA`, picking up host CUDA | `isaac_ros_common/cmake/isaac_ros_common-extras.cmake:22,39` | **Apache-2.0** (per-file header) | **us — PR prepared** |
| 13 | cuMotion's `find_dependency(Eigen3 3.3)` rejects Eigen 5, though Eigen 5 works | `cumotionConfig.cmake:27` (shipped in `isaac_ros_nitros`) | **Apache-2.0** (per-file header) | **us — patch prepared, verified against Eigen 5** |
| 14 | `ros_python_utils` raises at import time unless `ISAAC_ROS_WS` is set | `isaac_ros_manipulation_ros_python_utils/test_utils.py:62` | **Apache-2.0** | **us — patch prepared** |
| 15 | `topic_based_ros2_control` declared on jazzy, never released for jazzy | `isaac_ros_manipulation_*_robot_description/package.xml` | metadata in a public repo | **us, via PR** |
| 16 | Manipulation python packages under- and over-declare dependencies | `isaac_ros_launch_utils`, `isaac_common_py`, `ros_python_utils` | **Apache-2.0** / metadata | **us, via PR** |
| 17 | GXF headers include `magic_enum.hpp` by bare name, broken by magic_enum 0.9.7+ | `isaac_ros_gxf` prebuilt `gxf/core/expected_macro.hpp:24` | prebuilt blob, no source | **NVIDIA only** |
| 18 | Inference backends declared as `<depend>`, making TensorRT a *build* dependency of two packages that never call it | `isaac_ros_dope/package.xml:47`, `isaac_ros_centerpose/package.xml:49-50` | **Apache-2.0** | **us — patches prepared** |
| 19 | `isaac_ros_tensor_proc` links `isaac_ros_cvcuda_utils` without declaring it | `isaac_ros_tensor_proc/CMakeLists.txt:44`, `package.xml` | **Apache-2.0** | **us, via PR** |
| 20 | `install_isaac_ros_asset()` downloads models and runs `trtexec` as part of `ALL` | `isaac_ros_common/cmake/isaac_ros_common-extras-assets.cmake` | NVIDIA Isaac ROS Software License (no modification) | **NVIDIA only** |
| 21 | `isaac_ros_triton` defaults x86_64 to an unreachable internal artifactory URL | `isaac_ros_triton/CMakeLists.txt:20-22` | **Apache-2.0** | **NVIDIA** — needs a public x86_64 tarball to point at |

Only #4b, #5, #11, #17, #20 and #21 need NVIDIA to hold the pen — #4b because the intended license is
genuinely ambiguous from outside and we will not guess at it, and #11 because it is a
tagging and source-release decision in your repo. Item 2 has both a consumer-side fix we
can PR today and a cleaner root-cause fix only NVIDIA can make.

**Nothing here now stops a package from existing.** #13 looked like it did — cuMotion
appeared to be locked to Eigen 3 while ROS moves to Eigen 5 — until we built the stack
against Eigen 5.0.1 and checked cuMotion's IK output against independently computed forward
kinematics: exact to 0.000 mm. It is a CMake over-constraint, not an ABI wall. The one thing
we would still like from NVIDIA is confirmation of that reading.

---

## 1. `cuvslam2.h` is not self-contained — fails to compile on GCC 13+

**Severity:** blocks source builds of `isaac_ros_visual_slam` on modern toolchains.

`isaac_ros_nitros/lib/cuvslam/include/cuvslam/cuvslam2.h` declares

```cpp
struct Distortion {
  enum class Model : uint8_t {   // line 162
    Pinhole, Fisheye, Brown, Polynomial,
  };
  ...
};
```

but its includes are only `<array> <functional> <memory> <optional> <string>
<string_view> <unordered_map> <vector>` — never `<cstdint>`. `uint8_t` arrives
transitively under GCC 13, and does not under GCC 15:

```
cuvslam2.h:162:14: error: use of enum 'Model' without previous declaration
cuvslam2.h:162:22: error: 'uint8_t' was not declared in this scope
cuvslam2.h:162:30: error: default member initializer for unnamed bit-field
cuvslam2.h:169:3:  error: 'Model' does not name a type
cuvslam2.h:231:14: error: use of enum 'Encoding' without previous declaration
```

**Fix:** add `#include <cstdint>` to `cuvslam2.h`. One line.

Our workaround is `-include cstdint` in `CXXFLAGS`, which we would rather not carry.
This will also start biting NVIDIA directly as soon as the reference toolchain moves
past GCC 13.

---

## 2. Three `nvv4l2` libraries have no `DT_SONAME`, so consumers bake in absolute paths

**Severity:** made `isaac_ros_h264_decoder` unusable outside `/usr`. The only
non-relocatable component we found in the entire stack.

`libdecoder_node.so` carries **absolute paths as `DT_NEEDED` entries**:

```
$ readelf -d libdecoder_node.so | grep NEEDED
  /usr/lib/x86_64-linux-gnu/libnvbufsurface.so
  /usr/lib/x86_64-linux-gnu/libnvbuf_fdmap.so
  /usr/lib/x86_64-linux-gnu/libnvbufsurftransform.so
```

so loading it anywhere else fails:

```
Failed to load library: dlopen error: /usr/lib/x86_64-linux-gnu/libnvbufsurface.so:
cannot open shared object file: No such file or directory
```

### Root cause

Those three libraries in the `nvv4l2` package ship **without a `DT_SONAME`**:

```
libnvbufsurface.so         SONAME: <NONE>
libnvbuf_fdmap.so          SONAME: <NONE>
libnvbufsurftransform.so   SONAME: <NONE>
libnvv4l2.so               SONAME: libv4l2.so.0     <- has one, works fine
libcuvidv4l2.so            SONAME: <NONE>
```

`isaac_ros_h264_decoder/CMakeLists.txt` links them by absolute path:

```cmake
set_property(TARGET nvbuf_fdmap          PROPERTY IMPORTED_LOCATION /usr/lib/x86_64-linux-gnu/libnvbuf_fdmap.so)
set_property(TARGET nvbufsurface         PROPERTY IMPORTED_LOCATION /usr/lib/x86_64-linux-gnu/libnvbufsurface.so)
set_property(TARGET nvbufsurftransform   PROPERTY IMPORTED_LOCATION /usr/lib/x86_64-linux-gnu/libnvbufsurftransform.so)
set_property(TARGET nvv4l2               PROPERTY IMPORTED_LOCATION /usr/lib/x86_64-linux-gnu/libnvv4l2.so)
set_property(TARGET cuvidv4l2            PROPERTY IMPORTED_LOCATION /usr/lib/x86_64-linux-gnu/libcuvidv4l2.so)
```

When a shared library has no `DT_SONAME`, the linker has no name to record, so it falls
back to writing the path it was given. `libnvv4l2.so` has a soname and comes out as a
plain `libv4l2.so.0`; the three without one come out absolute. Same CMake pattern, two
different outcomes — which is why the failure looks arbitrary.

The `aarch64` branch has the same shape with `/usr/lib/aarch64-linux-gnu/nvidia/...`, so
Jetson is affected identically.

### You already do this for GXF

`gxf/build_install_gxf_release.sh` patches sonames into every GXF library, for
exactly this reason:

```bash
# Patchelf SONAMEs into shared libraries for name resolution
print_info "Patching SONAME into GXF shared libraires"
SOLIB_FILEPATHS=( `find ${TARGET_GXF_DIR} -name "libgxf_*.so"` )
for SOLIB_FILEPATH in "${SOLIB_FILEPATHS[@]}"
do
  SONAME=${SOLIB_FILEPATH##*/}
  chmod +w ${SOLIB_FILEPATH}
  patchelf --set-soname ${SONAME} ${SOLIB_FILEPATH}
done
```

So this is not a design disagreement — the practice, the rationale ("for name
resolution") and the tooling are already established in your own release process. The
`nvv4l2` libraries simply are not covered by it.

### Two fixes

**Root cause, NVIDIA only:** give the `nvv4l2` libraries a `DT_SONAME`. The existing
CMake then works unchanged and every downstream consumer is fixed at once. This is
exactly what `build_install_gxf_release.sh` already does for GXF.

**Consumer side, Apache-2.0, PR ready:** link the three by name against a search
directory instead of by absolute path. Measured against a deliberately soname-less
library:

| how it is linked | resulting `DT_NEEDED` |
|---|---|
| absolute path on the link line | `/abs/path/libfoo.so` |
| `-L<dir> -l:libfoo.so` | `libfoo.so` |
| absolute path, library **has** a soname | `libfoo.so` (the soname) |

Note for anyone reaching for the obvious CMake knob first: **`IMPORTED_SONAME` does
not help here.** We tried it and measured no change — with the library still linked by
absolute `IMPORTED_LOCATION`, the `DT_NEEDED` stayed absolute whether the property was
set or not. The fix has to change how the library is *linked*, not just annotate the
imported target.

Our PR changes only the x86_64 branch. The aarch64 branch keeps the absolute-path form,
because the Jetson `nvbuf_fdmap` is versioned (`libnvbuf_fdmap.so.1.0.0`) and we could
not verify whether an unversioned symlink sits beside it — so `-l:` is not assumed to
resolve there. That branch would benefit from the same change if you can confirm the
layout.

---

## 3. GXF's third-party fetch points at a host with no public DNS

**Severity:** the documented external source build of GXF cannot work as shipped.

`gxf/com_nvidia_gxf/third_party/cmake/*.cmake` fetch dependencies from
`urm.nvidia.com`, e.g.

```cmake
ExternalProject_Add(pybind11
    URL "https://urm.nvidia.com/artifactory/sw-isaac-gxf-generic-local/external/pybind11-2.11.1.tar.gz"
    URL_HASH "SHA256=4744701624538da603dde2b533c5a56fac778ea4773650332fe6701b25f191aa"
    ...)
```

`urm.nvidia.com` has **no public DNS record** (`Could not resolve host`), so these
fetches fail for anyone outside NVIDIA's network. `gxf/README.md` documents this build
as something "developers could use".

Mitigating: 15 of the 16 third-party modules are guarded, so passing
`-D<dep>_ROOT=...` avoids the fetch entirely and lets a system/conda copy be used —
which is how we build it. Two notes:

- `Boost.cmake` has no such guard; it calls `find_package(Boost 1.74.0 REQUIRED)`
  directly, with the comment `#TODO GXF depends on 1.80 but apt-get installs 1.74`.
- `yaml-cpp.cmake` and `magic_enum.cmake` fetch from `developer.nvidia.com` and GitHub
  respectively, which *are* reachable — so the internal host is not used uniformly.

**Fix:** point the remaining URLs at a public mirror, or document the
`-D<dep>_ROOT` path as the supported route for external builders.

---

## 4. Four packages have a malformed `<license>` tag — and we cannot tell what they mean

**Severity:** low technically, but three of them are genuinely ambiguous and we would
rather not guess on your behalf.

### 4a. Stray quotes — unambiguous, PR ready

`isaac_ros_nova/isaac_ros_data_validation/package.xml`:

```xml
<license>"NVIDIA Isaac ROS Software License"</license>
```

The name is right, the quotes break exact-match license tooling. Every other package
using this license writes it unquoted. (Its `<description>` is quoted the same way.)

### 4b. A copyright block instead of a license name — needs your call

```
isaac_ros_nova/isaac_ros_data_recorder
isaac_ros_nova/isaac_ros_nova_recorder
isaac_ros_manipulation/isaac_ros_manipulation_dnn_policy
```

Their `<license>` element contains the file header instead of a license identifier:

> Copyright (c) 2023-2024, NVIDIA CORPORATION. All rights reserved. NVIDIA
> CORPORATION and its licensors retain all intellectual property and proprietary
> rights in and to this software … Any use, reproduction, disclosure or distribution
> of this software and related documentation without an express license agreement
> from NVIDIA CORPORATION is strictly prohibited.

Read literally that grants nothing at all, which is almost certainly not the intent.
But **the surrounding evidence points two different ways**, so we are not proposing a
value:

- Both repos ship an **Apache License** as their top-level `LICENSE`, and neither has a
  per-package `LICENSE` file.
- In `isaac_ros_nova`, 14 of 17 packages declare `Apache-2.0`.
- In `isaac_ros_manipulation`, 15 declare `Apache-2.0` but 2
  (`isaac_ros_manipulation_robot_utils`, `isaac_ros_manipulation_ros_python_utils`)
  declare `NVIDIA Isaac ROS Software License`.

So both repos genuinely mix the two licenses, and from outside there is no way to tell
which of the two these three packages belong to. Could you confirm, and we will send
the PR — or fix it directly, whichever is easier.

For packaging purposes we currently treat all three as non-redistributable, which is
the conservative reading. If they are meant to be Apache-2.0 that is a meaningful
difference to anyone redistributing Isaac ROS.

---

## 5. Absolute `/opt/ros/jazzy` paths baked into the ament resource index

**Severity:** blocks relocating an installed tree; expected for a deb, worth knowing.

`share/ament_index/resource_index/isaac_ros_common_cmake_path/isaac_ros_common`
contains the literal string `/opt/ros/jazzy/share/isaac_ros_common/cmake`, and every
Isaac `CMakeLists.txt` does

```cmake
ament_index_get_resource(ISAAC_ROS_COMMON_CMAKE_PATH isaac_ros_common_cmake_path isaac_ros_common)
include("${ISAAC_ROS_COMMON_CMAKE_PATH}/isaac_ros_common-version-info.cmake")
```

so any downstream configure hard-fails if the tree is not at `/opt/ros/jazzy`.

**Fix:** store the path relative to the ament prefix and resolve it at read time. Easy
for us to work around (we rewrite it at package time), but it is the difference
between a relocatable install and a fixed one.

---

## 6. The `negotiated` deb installs into a multiarch subdirectory

**Severity:** minor, and it is your packaging rather than upstream's.

`ros-jazzy-negotiated` installs `libnegotiated.so` into `lib/x86_64-linux-gnu/`, and its
generated export `share/negotiated/cmake/export_negotiatedExport.cmake:85` asserts the
file exists at exactly `${_IMPORT_PREFIX}/lib/x86_64-linux-gnu/libnegotiated.so`.
Flattening that level — which any non-Debian layout does — turns it into a hard
configure error. It is the only package in the closure using the multiarch subdirectory.

Building the same upstream source ourselves installs to plain `lib/libnegotiated.so`, so
this comes from the deb build configuration (`CMAKE_INSTALL_LIBDIR`), not from
`osrf/negotiated`. Nothing to fix upstream at OSRF.

Worth aligning with the other packages anyway, since the `EXISTS` assertion makes the
resulting package non-relocatable.

## 7. Question: TensorRT 10.9 is a CUDA 12.8 build, while 4.5 is CUDA 13

Not a bug, just unclear intent. Isaac ROS 4.5 targets CUDA 13.0 throughout —
`isaac_ros_gxf` ships `gxf_x86_64_cuda_13_0`, `libcudnn9-cuda-13` is a declared
dependency. But the six TensorRT-dependent debs require `libnvinfer10`, and the only
`libnvinfer10` in the CUDA repo is `10.9.0.34-1+cuda12.8`. `libnvinfer11` is the CUDA
13 build (`11.1.0.106-1+cuda13.3`).

Is mixing the CUDA 12.8 TensorRT into a CUDA 13 process intended and tested, or is a
TensorRT 11 migration pending? It changes what a packager should pin.

---

## 8. Question: 15 `gxf_isaac_*` extensions declare Apache-2.0 but ship no source

Of the 18 `gxf_isaac_*` packages in `isaac_ros_nitros`, 15 are
`add_library(<name> INTERFACE)` targets whose CMakeLists only `install()` a prebuilt
`.so` from `lib/gxf_x86_64_cuda_13_0/`. Only `camera_utils`, `utils` and `gems`
actually build from source.

All 18 declare `<license>Apache-2.0</license>`. Apache-2.0 does not oblige anyone to
publish source, so this is not a violation — but it is surprising, and if the source
were released those 15 would become buildable, which would shrink the prebuilt floor
considerably. Is that on the roadmap, or is the Apache-2.0 tag on the wrapper only?

---

## 11. Every `v4.x` tag on the public GXF repo points at 3.2-era source

**Severity:** this is the single thing keeping the largest binary package in our
prebuilt floor. Unlike #8, the source here *is* published — it is just four minor
versions and one major version stale, and the tags say otherwise.

`isaac_ros_gxf` is the biggest package we repack: 22 GXF libraries, 56 `.so` files.
`NVIDIA-ISAAC-ROS/gxf` looks like exactly the source for it — 377 `.cpp`, 225 `.hpp`,
and its subdirectories map one-to-one onto the libraries the deb ships (`core`, `std`,
`cuda`, `multimedia`, `serialization`, `npp`, `stream`, `ucx`, `logger`, `network`,
`rmm`, `app`, `behavior_tree`, `python_codelet`, `test`, `sample`). So we tried to
source-build it.

It is the wrong version. Same file, same line, both sides:

```
Isaac ROS 4.5 shipped headers      gxf/core/gxf.h:183  #define kGxfCoreVersion "5.1.0"
public source, newest tag v4.4-0   gxf/core/gxf.h:183  #define kGxfCoreVersion "4.1.0"
```

And the tags do not distinguish releases at all. These all resolve to the **same
commit**, `daf1810358301f642374dfb3d725be349bba5ec0`:

```
refs/heads/main
refs/tags/v3.2.0   refs/tags/v3.2-1 … v3.2-13
refs/tags/v4.0-0   refs/tags/v4.0-1
refs/tags/v4.1-0
refs/tags/v4.2-0
refs/tags/v4.3-0
refs/tags/v4.4-0
```

`com_nvidia_gxf/CMakeLists.txt` there declares `VERSION 4.1.0`. There is no `v4.5`
tag. So a tag named for Isaac ROS 4.4 delivers the GXF that shipped with Isaac ROS
3.2, and `main` has not moved either.

### Why the mismatch is not something a packager can work around

GXF 4.1.0 built from source would have to coexist with `isaac_ros_nitros` and the 15
prebuilt `gxf_isaac_*` extensions, all compiled against 5.1.0 — across a 107-function
C API plus the C++ base classes those extensions derive from.

There is no version gate to catch it. `kGxfCoreVersion` is recorded in
`DefaultExtension::gxf_core_version_` and surfaced through `GxfRuntimeInfo`
(`runtime.cpp:362`), but nothing compares it when an extension is loaded. A
major-version mismatch therefore links quietly and fails later at runtime, rather than
being rejected at load. That is the failure mode we would least like to ship.

### What would help, in order

1. **Publish the GXF 5.1.0 source** that Isaac ROS 4.5 actually ships, or tag it. This
   is the one change that moves `isaac_ros_gxf` — 56 libraries — out of the prebuilt
   floor entirely.
2. **Fix the tags** regardless. Even without a 5.1.0 release, `v4.4-0` resolving to
   3.2-era source is misleading on its own, and it cost us a source-build attempt to
   discover. If the 4.x tags are only meant to mark "compatible with Isaac ROS 4.x",
   saying so in the README would do.

Worth noting what is *not* the obstacle, since these are the usual suspects: the
third-party dependency fetches are fine. 15 of the 16 modules in
`third_party/cmake/` are guarded with `if(DEFINED <dep>_DIR OR <dep>_ROOT)`, so
`-D<dep>_ROOT=` avoids every `urm.nvidia.com` fetch (see #3), and `Boost.cmake` calls
`find_package` directly without fetching. The only build-config friction is that
`CMakePresets.json` offers no CUDA 13 preset — the newest is `x86_64_cuda_12_2`, for a
stack that is CUDA 13 throughout (see #7).

---

## 12. `isaac_ros_common` resurrects CMake's removed `FindCUDA`, and silently adopts the build machine's CUDA

**Severity:** breaks every Isaac ROS package on a machine without `/usr/local/cuda`, and
on machines that have one, quietly compiles against it instead of the toolkit the build
was configured with. This one bit us for real — see the note at the end.

`isaac_ros_common/cmake/isaac_ros_common-extras.cmake` does:

```cmake
# The FindCUDA module is removed
if(POLICY CMP0146)
  cmake_policy(SET CMP0146 OLD)
endif()
...
find_package(CUDA REQUIRED)
include_directories("${CUDA_INCLUDE_DIRS}")
```

`FindCUDA` was deprecated in CMake 3.10 and **removed in CMake 4.0**. The comment is
accurate about that, and the file keeps it alive by forcing a deprecated policy to `OLD`.
CMake already warns this will stop working:

```
CMake Warning (deprecated) at isaac_ros_common-extras.cmake:23 (cmake_policy):
  The OLD behavior for policy CMP0146 will be removed from a future version of CMake.
```

This file is included by `isaac_ros_commonConfig.cmake`, so it runs for **every** package
that calls `ament_auto_find_build_dependencies()`. When `CMP0146` goes, the whole stack
stops configuring at once.

### The present-day problem

`FindCUDA` finds the toolkit through `CUDA_TOOLKIT_ROOT_DIR` and expects a monolithic
layout. Against a component-based CUDA installation it simply fails:

```
CMake Error at cmake-4.4/Modules/FindCUDA.cmake:883 (message):
  Specify CUDA_TOOLKIT_ROOT_DIR
Call Stack (most recent call first):
  isaac_ros_common-extras.cmake:39 (find_package)
  isaac_ros_commonConfig.cmake:41 (include)
  ament_auto_find_build_dependencies.cmake:67 (find_package)
```

Worse is the case where it *succeeds*. On any machine with `/usr/local/cuda`, `FindCUDA`
picks that up with no diagnostic — **even when it is a different CUDA major version than
the build was configured against**. We shipped a package that referenced
`cudaGetDeviceProperties_v2` because a CUDA 12.9 header at `/usr/local/cuda` reached a
CUDA 13 build this way. CUDA 12's `cuda_runtime_api.h` aliases
`cudaGetDeviceProperties` to the `_v2` name; CUDA 13 dropped the alias, so
`libcudart.so.13` does not export it and the node failed at `dlopen` with an undefined
symbol. Nothing about the build looked wrong.

### Fix, PR ready

Use `FindCUDAToolkit` (CMake 3.17+), which discovers component-based installations and
honours `CMAKE_FIND_ROOT_PATH` / `CMAKE_PREFIX_PATH`:

```
find_package(CUDA REQUIRED)  ->  find_package(CUDAToolkit REQUIRED)
CUDA_INCLUDE_DIRS            ->  CUDAToolkit_INCLUDE_DIRS
CUDA_VERSION                 ->  CUDAToolkit_VERSION
```

and delete the `CMP0146` block, which exists only to keep `FindCUDA` alive. That is the
whole change: 5 insertions, 10 deletions. Prepared as
`upstream/isaac_ros_common` branch `fix/findcudatoolkit`, DCO signed off, and verified by
building `isaac_ros_common` plus its consumers against a component-based CUDA 13.3
toolkit where `find_package(CUDA)` fails outright.

This file carries its own `SPDX-License-Identifier: Apache-2.0` header — two of the four
`.cmake` files in the package do — so unlike #5 it is modifiable, and we can send the PR.

### One consequence worth knowing when you review it

Fixing the discovery exposes a second thing that the host-CUDA fallback was masking.
Because these extras call `find_package(CUDAToolkit REQUIRED)` unconditionally, a package
needs a CUDA toolkit at configure time **even if it uses no CUDA at all**.
`gxf_isaac_gems` is the clearest example: header-only, no CUDA anywhere in its own
`CMakeLists.txt`, and it still cannot configure without `cudart`. That is arguably fine as
a design choice, but it is undocumented, and it means "depends on `isaac_ros_common`"
silently implies "depends on the CUDA toolkit". Making the CUDA requirement conditional,
or documenting it, would help anyone packaging this stack.

---

## 13. cuMotion's Eigen version request is stricter than its ABI needs

**Severity:** looked like a hard blocker on `isaac_ros_cumotion_moveit`; turned out to be a
metadata over-constraint. Two lines of fix, and **we ran it against Eigen 5.0.1 and checked
the answers**. Found while packaging `isaac_ros_manipulation`.

**It is not only cuMotion.** `find_package(Eigen3 3.3 REQUIRED NO_MODULE)` appears verbatim
in **18** packages across this corpus -- 13 NITROS type adapters, 3 GXF extensions,
`isaac_ros_depth_image_proc`, `isaac_ros_detectnet`, `isaac_ros_grounding_dino`,
`isaac_ros_cumotion_robot_segmenter` and the NITROS core -- and every one of them fails to
configure against the Eigen 5.0.1 robostack-jazzy now ships:

```
CMake Error at CMakeLists.txt:40 (find_package):
  Could not find a configuration file for package "Eigen3" that is compatible with
  requested version "3.3".
    .../share/eigen3/cmake/Eigen3Config.cmake, version: 5.0.1
      The version found is not compatible with the version requested.
```

The mechanism is the same in all of them, and worth stating plainly because it is easy to
write by accident: **in config mode a version argument is a ceiling as well as a floor.**
Eigen ships a `SameMajorVersion` `Eigen3ConfigVersion.cmake`, so "3.3" does not mean "3.3
or newer" -- it means "3.x", and Eigen 5 is *rejected*. `NO_MODULE` forces config mode,
which also rules out the usual escape hatch (`ros-jazzy-eigen3-cmake-module`'s module-mode
`FindEigen3.cmake`, which does treat the version as a floor). Dropping the number, keeping
`REQUIRED`, satisfies every Eigen these packages actually work with. `scripts/gen_source.py`
does that as the `eigenfloor` build trait.

> **Result first, because it changes the ask.** Compiled against Eigen 5.0.1 and linked
> against the Eigen 3 `libcumotion.so.1.1.0` as shipped, cuMotion loads, plans, and solves
> IK **exactly**: the returned joint values put the gripper 0.000 mm from the requested
> pose (`manip/fk_check.py`, independent numpy forward kinematics). So the request below is
> not "rebuild cuMotion" — it is "let consumers use Eigen 5, because it already works".

`libcumotion.so.1.1.0`, shipped inside `isaac_ros_nitros`, exports an API made of Eigen
types. 23 of its 31 headers include `Eigen/Core`, and the types appear in *virtual*
signatures — so they are part of the vtable ABI, not an implementation detail:

```cpp
// cumotion/kinematics.h
virtual bool withinCSpaceLimits(const Eigen::VectorXd &cspace_position, ...) const = 0;
// cumotion/trajectory.h
virtual bool sample(double t, Eigen::VectorXd *cspace_position, ...) const = 0;
// cumotion/rotation3.h
explicit Rotation3(const Eigen::Quaterniond &quaternion, bool skip_normalization = false);
```

`cumotionConfig.cmake` states the requirement:

```cmake
include(CMakeFindDependencyMacro)
find_dependency(Eigen3 3.3)
```

Eigen's own `Eigen3Config.cmake` uses `SameMajorVersion` compatibility, so a `3.3` request
**rejects** Eigen 5:

```
Could not find a configuration file for package "Eigen3" that is compatible
with requested version "3.3".
  $PREFIX/share/eigen3/cmake/Eigen3Config.cmake, version: 5.0.1
```

Eigen 5.0 shipped in 2025 and ROS distributions are moving to it: `robostack-jazzy`'s
`moveit_core` now carries `eigen-abi >=5.0.1.80,<5.0.1.81`. Taken at face value that costs
three packages — `isaac_ros_cumotion_moveit` (needs `moveit_core`),
`isaac_ros_manipulation_gear_assembly` (needs `ur_robot_driver` →
`joint_trajectory_controller` → `rsl`) and, through the first,
`isaac_ros_manipulation_flexiv_driver_utils`.

### What actually happens with Eigen 5

Three of cuMotion's entry points that our code calls have Eigen types in their signatures.
Demangled from `libcumotion_impl.so`, compiled against Eigen 5.0.1:

```
U cumotion::Pose3::Pose3(cumotion::Rotation3 const&, Eigen::Matrix<double, 3, 1, 0, 3, 1> const&)
U cumotion::Obstacle::AttributeValue::AttributeValue(Eigen::Matrix<double, 3, 1, 0, 3, 1> const&)
U cumotion::Rotation3::Rotation3(Eigen::Quaternion<double, 0> const&, bool)
```

Those mangled names are what the Eigen 3 `libcumotion.so.1` exports, unchanged —
`Eigen::Matrix<double,3,1,0,3,1>` and `Eigen::Quaternion<double,0>` have the same template
signature in both versions, so they link. They are also passed by const reference, so what
crosses the boundary is a pointer to three or four doubles, and that layout did not change
either. `dlopen(..., RTLD_NOW)` resolves every symbol in the plugin and the planner.

Then the numbers. `manip/ik.sh` asks cuMotion for IK on the UR5e + Robotiq 2F-85 it ships,
and `manip/fk_check.py` recomputes the pose from the returned joint angles with an
independent numpy forward-kinematics implementation:

| built against | IK solutions | position error at the gripper |
|---|---|---|
| Eigen 3.4.0 (matching the shipped `.so`) | 26 | 0.026 mm |
| **Eigen 5.0.1** | 26 | **0.000 mm** |

Same solution count, both geometrically correct, and the two builds return *different*
branches of the 26 — which is expected when `num_solutions_to_return: 1` picks one from a
parallel search, and is stable across runs within a build.

### So the fix is one line, in the file that carries the constraint

`recipes/ros-jazzy-isaac-ros-nitros/build.sh` drops the floor from the config it installs:

```bash
sed -i 's/find_dependency(Eigen3 3\.3)/find_dependency(Eigen3)/' \
  "${PREFIX}/share/isaac_ros_nitros/cumotion/lib/cmake/cumotion/cumotionConfig.cmake"
```

It asserts the old text is present first, so if a future cuMotion changes or removes the
constraint the build fails loudly rather than silently skipping the patch. Fixing it in the
config rather than in each consumer means it holds for anything that finds cuMotion, now or
later, and `find_dependency` without a version still accepts Eigen 3.

Worth knowing if you reach for the alternative: ROS's `eigen3_cmake_module` ships a
module-mode `FindEigen3.cmake` that treats a requested version as a floor rather than
applying Eigen's same-major rule, so putting its `Modules` directory on `CMAKE_MODULE_PATH`
*also* makes the build pass. That route is order-dependent and silent — it works only if
something found `Eigen3` unversioned first, which is exactly why
`isaac_ros_cumotion_object_attachment` built clean against Eigen 5 while `isaac_ros_cumotion`
failed in the same tree, for reasons neither package states. We used it, understood it, and
then removed it in favour of the line above.

**What would help, in order of preference:**

1. **Relax `find_dependency(Eigen3 3.3)` in `cumotionConfig.cmake`** — drop the version, or
   raise the ceiling. One line, and it is the whole issue.
2. **Say which Eigen each cuMotion release was built against**, and confirm whether the
   layouts above are considered ABI. We have evidence it works; you have the source.

One caveat we cannot close from outside: this is verified for the code paths `manip/`
exercises (robot model loading, collision spheres, IK, trajectory-optimizer construction),
not for every entry point in a 31-header API.

## 14. `isaac_ros_manipulation_ros_python_utils` cannot be imported without `ISAAC_ROS_WS`

**Severity:** breaks `import isaac_ros_manipulation_ros_python_utils` in any environment
that does not export a workspace variable — which is every non-container install. Trivial
fix, Apache-2.0 file, **patch prepared**.

`isaac_ros_manipulation_ros_python_utils/test_utils.py` raises at module scope:

```python
ISAAC_ROS_WS = os.environ.get('ISAAC_ROS_WS')
if ISAAC_ROS_WS is None:
    raise RuntimeError('ISAAC_ROS_WS environment variable is not set')
```

`__init__.py` re-exports `test_utils`, so the raise fires on plain

```console
$ python -c "import isaac_ros_manipulation_ros_python_utils"
RuntimeError: ISAAC_ROS_WS environment variable is not set
```

and takes down every package that imports the utilities with it —
`isaac_ros_manipulation_orchestration`, `_robot_utils`, `_pick_and_place`, `_servers` and
both driver-utility packages. A smoke test as simple as importing the module cannot pass.

The variable has exactly one use in the file: composing an asset path for the
gear-assembly FoundationPose mesh. Moving the check to that use keeps the error for the
code path that needs the assets and lets the library import.
`recipes/ros-jazzy-isaac-ros-manipulation-ros-python-utils/patches/0001-defer-isaac-ros-ws-check.patch`
does that, in six lines.

## 15. `topic_based_ros2_control` is declared on jazzy but was never released for jazzy

**Severity:** `rosdep install` cannot resolve the dependencies of two packages on the
target distro. Metadata only.

`isaac_ros_manipulation_ur_robot_description` and
`isaac_ros_manipulation_flexiv_robot_description` both declare

```xml
<exec_depend>topic_based_ros2_control</exec_depend>
```

`topic_based_ros2_control` is in `ros/rosdistro` for **humble only** (0.2.0-1). There is no
jazzy release, and ros-controls has since superseded it with
`topic_based_hardware_interfaces`. Isaac ROS 4.5 targets jazzy, so on the documented
distribution these two packages have a dependency no package manager can satisfy — it works
inside NVIDIA's container because the source is vendored into the workspace.

Either depend on the successor, note that the source has to be cloned, or ask
ros-controls for a jazzy release of the original. We build it from the upstream commit
(`recipes/ros-jazzy-topic-based-ros2-control`) because it is BSD-3-Clause, four
dependencies wide, and builds clean on jazzy as-is.

## 16. The manipulation python packages under- and over-declare their dependencies

**Severity:** cosmetic for a container build, load-bearing for anyone resolving
dependencies from metadata. Metadata only.

Three separate patterns, all found by building the packages and watching what actually
failed to import:

- **Under-declared.** `isaac_ros_launch_utils` declares exactly one dependency,
  `<build_depend>isaac_ros_common</build_depend>`, while importing `launch`, `launch_ros`,
  `launch_xml`, `ament_index_python` and `yaml`. Its `package.xml` describes a package that
  cannot import itself. `isaac_common_py` is the same shape.
- **Over-declared.** `isaac_ros_manipulation_ros_python_utils` declares
  `python3-torch-pip-shim`, and no module in it imports torch. On a metadata-driven install
  that is a multi-gigabyte dependency for nothing.
- **Test harness as a runtime dependency.** The same package declares `isaac_ros_test` as a
  full `<depend>`, not a `<test_depend>` — and it is right to, because `test_utils.py`
  imports `IsaacROSBaseTest` at module level. But `isaac_ros_test` pulls torch, onnx and
  onnxscript, so a test harness ends up in the runtime closure of the whole manipulation
  stack. Splitting the test helpers out of `__init__.py` would cost nothing and drop the
  runtime closure substantially.

We derive python run dependencies from module-level imports rather than from `package.xml`
(`scripts/gen_source.py`), because the manifests are not reliable enough to resolve
against. Function-level imports are treated as optional, which is what they are —
`ros_python_utils` reaches for the UR and Flexiv driver utilities that way, and both of
those depend on it in turn, so taking those as hard dependencies would invent a cycle.

## 17. GXF's vendored headers include `magic_enum.hpp` by bare filename

**Severity:** breaks every source build that touches a GXF header as soon as `magic_enum`
0.9.7+ is in the environment. Bit us on a rebuild that had worked weeks earlier with nothing
changed on our side.

`isaac_ros_gxf` ships prebuilt headers, and `gxf/core/expected_macro.hpp:24` has:

```cpp
#include "magic_enum.hpp"  // NOLINT(build/include)
```

magic_enum moved its headers into a `magic_enum/` subdirectory in 0.9.7 (conda-forge follows
upstream), so the include stops resolving:

```
$PREFIX/share/isaac_ros_gxf/gxf/include/gxf/core/expected_macro.hpp:24:10:
  fatal error: magic_enum.hpp: No such file or directory
```

Two things make this worse than a version bump usually is. The header is a prebuilt blob, so
a consumer cannot fix the include; and it is not target-scoped, so linking
`magic_enum::magic_enum` does not help — the directory has to be on `CXXFLAGS` for every
translation unit that transitively includes a GXF header. Our workaround is
`-I$PREFIX/include/magic_enum` in `recipes/ros-jazzy-isaac-ros-nitros/build.sh`.

`#include <magic_enum/magic_enum.hpp>` upstream, with a fallback for older versions, would
close it.

---

## Appendix: not NVIDIA's, but affects running your benchmarks

`launch_testing`'s pytest plugin declares `pytest_pycollect_makemodule(path, parent)`,
the pre-pytest-8 signature, and fails plugin validation on current pytest:

```
PluginValidationError: Plugin 'launch_testing' for hook 'pytest_pycollect_makemodule'
Argument(s) {'path'} are declared in the hookimpl but can not be found in the hookspec
```

So `pytest isaac_ros_*_benchmark.py` cannot run; `launch_test` must be used instead.
A ROS 2 upstream issue, but it will hit anyone running `isaac_ros_benchmark` outside
your pinned container.

Also: `ros2_benchmark` resolves datasets only through
`${ISAAC_ROS_WS}/src/ros2_benchmark/assets`, and the documented `assets_root:=` launch
argument does not override it.

Finally, the benchmark scripts say they need
`assets/datasets/r2b_dataset/r2b_storage` without saying where it lives. It is on NGC
under `r2bdataset2023`, while `r2b_galileo` is under `r2bdataset2024` — worth naming
the resource in the docstring.

## 18. TensorRT is a *build* dependency of two packages that never call it

**Severity:** blocks `isaac_ros_dope` and `isaac_ros_centerpose` from being built at all
anywhere TensorRT (and, for centerpose, Triton) is unavailable — which is every platform
NVIDIA does not ship `libnvinfer` debs for, and every packaging of the stack outside your
container. Apache-2.0 metadata, one line each, **patches prepared**.

Both packages declare their inference backend as a build dependency:

```xml
<!-- isaac_ros_dope/package.xml -->
<depend>isaac_ros_tensor_rt</depend>

<!-- isaac_ros_centerpose/package.xml -->
<depend>isaac_ros_tensor_rt</depend>
<depend>isaac_ros_triton</depend>
```

Neither uses them. `isaac_ros_dope` builds one target from one source file, and between
that file and its header the complete include list is `ament_index_cpp`, `Eigen/Dense`,
`geometry_msgs`, `isaac_ros_common/qos.hpp`, `isaac_ros_nitros/nitros_node.hpp`,
`isaac_ros_nitros_tensor_list_type`, `isaac_ros_tensor_list_interfaces`, `opencv2`,
`rclcpp`, `rclcpp_components`, `sensor_msgs`, `tf2_ros`, `vision_msgs`.
`isaac_ros_centerpose` builds two targets from five source files, with the same result.
Not one header from either backend. The decoders take a `TensorList` off a topic and
solve PnP on it; the inference is a separate composable node the launch file puts in the
same container. `grep -r 'tensor_rt\|nvinfer\|triton'` over both `src/` and `include/`
trees returns nothing.

Because `ament_auto_find_build_dependencies()` turns every `<depend>` into a REQUIRED
`find_package`, a package whose entire dependency set is OpenCV, Eigen and NITROS cannot
be *configured* without TensorRT present. `ament_auto_add_library` then links every found
dependency, so the shipped `.so` also picks up a `DT_NEEDED` on a library it has no symbol
from. For centerpose it is worse: TensorRT and Triton are *alternative* backends chosen by
which launch file you run, and it has to build against both.

`<exec_depend>` is what package format 3 has for this. It keeps `rosdep install` and the
launch files exactly as they are — exec dependencies are still installed — and lets the
build need only what the code includes. Two patches, one line and two lines:

- `recipes/ros-jazzy-isaac-ros-dope/patches/0001-tensor-rt-is-a-runtime-dependency.patch`
- `recipes/ros-jazzy-isaac-ros-centerpose/patches/0001-tensor-rt-and-triton-are-runtime-dependencies.patch`

With them applied, both packages build and every component loads — see `pose/`. This is
the same class of finding as #16, and it is the difference between two packages existing
and not existing.

## 19. `isaac_ros_tensor_proc` links a package it does not declare

**Severity:** hard configure failure outside a workspace that happens to have the package
already. Apache-2.0, one line.

`isaac_ros_tensor_proc/CMakeLists.txt` builds `reshape_node` with

```cmake
ament_target_dependencies(reshape_node rclcpp rclcpp_components isaac_ros_cvcuda_utils)
```

and `package.xml` never mentions `isaac_ros_cvcuda_utils`. Since
`ament_auto_find_build_dependencies()` only finds what the manifest declares, and
`ament_target_dependencies` hard-errors on a package `find_package` has not located,
configure fails outright rather than degrading. In a colcon workspace holding the whole of
Isaac ROS it is masked, because some sibling package pulls `isaac_ros_cvcuda_utils` in
first — build the package on its own and it fails.

The generator adds it explicitly (`EXTRA_DEPS` in `scripts/gen_source.py`) rather than
relying on a sibling; the manifest should declare it.

## 20. `install_isaac_ros_asset()` downloads models and runs `trtexec` during the build

**Severity:** `isaac_ros_foundationpose_models_install` cannot be built outside your dev
container. The function lives in `isaac_ros_common/cmake`, which is under the
proprietary header, so this one is **NVIDIA's to fix**.

`install_isaac_ros_asset(install_foundationpose_models)` does two things at build time:

1. `execute_process`es the asset script with `--print-install-paths` at *configure* time.
   Every path in that script derives from `$ISAAC_ROS_WS`, so with the variable unset —
   which it is in any environment that is not your container — configure aborts with

   ```
   CMake Error at .../isaac_ros_common-extras-assets.cmake:34 (message):
     ERROR: ISAAC_ROS_WS is not set.
   ```

2. Hangs the script off `add_custom_target(... ALL)`, so the default build target
   downloads `refine_model.onnx` and `score_model.onnx` from NGC behind a EULA prompt and
   runs `trtexec` over both.

Step 1 is a bug — a build should not require an environment variable that has no default.
Step 2 is a design question, and the answer matters more: a TensorRT engine plan is
specialised to the GPU, driver and TensorRT version that produced it, so a `.plan` baked
into a binary artifact is wrong for every machine except the builder's. Model download and
engine generation belong on the target system, which is also how your own documentation
describes them:

```console
ros2 run isaac_ros_foundationpose_models_install install_foundationpose_models.sh
```

A guard that keeps the `ament_index_register_resource` and skips the dry-run and the `ALL`
target when the assets cannot be fetched — or an opt-in
`-DISAAC_ROS_DOWNLOAD_ASSETS=ON` — would make the package buildable everywhere without
changing anything for container users.
`scripts/gen_source.py` does it consumer-side, as the `asset` build trait: it rewrites the
`install_isaac_ros_asset(<name>)` call to the `ament_index_register_resource()` the function
would have emitted, and drops the dry-run and the `ALL` target. That is a packaging
deviation rather than a fix, and deliberately so -- the fix cannot be made here, because
the function is in `isaac_ros_common/cmake` under the proprietary header.

Four packages need it -- `isaac_ros_foundationpose_models_install`,
`isaac_ros_rtdetr_models_install`, `isaac_ros_grounding_dino_models_install` and
`isaac_ros_peoplenet_models_install` -- and every Isaac repo tends to ship one, which is
why it is a rule rather than four identical patch files. All four write the call the same
way, with the asset name matching its script's basename; the generated build script asserts
that text is present before rewriting, so a change in shape upstream fails the build loudly
instead of quietly restoring the download.

## 21. `isaac_ros_triton` cannot be built on x86_64 outside NVIDIA

**Severity:** blocks `isaac_ros_triton` completely on x86_64 — not "needs a workaround",
blocks it, because the artifact it needs is not published anywhere public. The CMake is
Apache-2.0 and the fix is a one-line URL change, but only NVIDIA can supply the artifact
that URL should point at.

`isaac_ros_triton/CMakeLists.txt` picks a Triton Server tarball by architecture:

```cmake
if(CMAKE_SYSTEM_PROCESSOR STREQUAL "aarch64")
  set(_TRITON_BASE_URL "https://github.com/triton-inference-server/server/releases/download")
  set(TRITON_SERVER_TARBALL_URL "${_TRITON_BASE_URL}/v2.60.0/tritonserver2.60.0-agx.tar")
elseif(CMAKE_SYSTEM_PROCESSOR STREQUAL "x86_64" OR ...)
  set(_TRITON_BASE_URL "https://artifactory.pdx.nvidia.com/artifactory")
  set(_TRITON_PATH "sw-isaac-ros-generic-local/triton/tritonserver.2.60.tar.gz")
```

The aarch64 branch points at a public GitHub release. The x86_64 branch points at
`artifactory.pdx.nvidia.com`, which is an internal host — it does not resolve from outside
your network at all:

```console
$ curl -sI https://artifactory.pdx.nvidia.com/artifactory/sw-isaac-ros-generic-local/triton/tritonserver.2.60.tar.gz
HTTP 000   (DNS resolution failed)
```

`FetchContent` then fails, and since the package needs `libtritonserver.so` and
`tritonserver.h` from that tarball, there is no build without it.

`TRITON_SERVER_TARBALL_URL` is overridable, which is the saving grace — but there is
nothing public to override it *with*. The v2.60.0 release publishes
`tritonserver2.60.0-agx.tar` and `tritonserver2.60.0-igpu.tar`, both aarch64, plus a
clients tarball. Triton's x86_64 server is distributed as an NGC **container image**, not
as a tarball, so the two routes left to a downstream packager are extracting
`libtritonserver.so` out of a ~15 GB container layer, or building
`triton-inference-server/core` from source with its whole vendored `third_party` tree.
Both are disproportionate for one library, and neither is what the CMake intends.

**What would fix it:** publish the x86_64 server tarball alongside the aarch64 ones on the
Triton releases page (or anywhere public), and point the x86_64 branch at it. This is the
same class of problem as #3 (`urm.nvidia.com` unreachable in the GXF build) — an internal
URL that works inside NVIDIA and silently makes a public repository unbuildable outside
it. Worth a grep across the Isaac ROS repos for other `*.nvidia.com` hosts that are not
`developer.download.nvidia.com` or `github.com`.

This is why `isaac_ros_triton` is absent from this repository while
`isaac_ros_tensor_rt` is present: TensorRT's binaries are publicly downloadable and
TensorRT is the backend every Isaac ROS DNN pipeline actually defaults to. Triton is the
alternative backend for exactly one package (`isaac_ros_centerpose`, which also ships a
TensorRT launch file), so nothing in the stack is unreachable for want of it.
