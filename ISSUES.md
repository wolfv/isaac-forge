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

Only #4b, #5 and #11 need NVIDIA to hold the pen — #4b because the intended license is
genuinely ambiguous from outside and we will not guess at it, and #11 because it is a
tagging and source-release decision in your repo. Item 2 has both a consumer-side fix we
can PR today and a cleaner root-cause fix only NVIDIA can make.

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
