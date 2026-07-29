# Upstream PR branches

Forks of the NVIDIA Isaac ROS repos with the fixes from [`../ISSUES.md`](../ISSUES.md)
prepared as commits. Nothing has been opened as a PR yet.

All commits are DCO signed-off, which Isaac ROS `CONTRIBUTING.md` requires.

See [`PR_LINKS.md`](PR_LINKS.md) for the compare URLs.

| Repo | Branch | Issue | Change | Verified |
|---|---|---|---|---|
| `isaac_ros_nitros` | `fix/cuvslam2-missing-cstdint` | #1 | `+#include <cstdint>` in `cuvslam2.h` | **verified** — visual_slam compiles and links against the patched header with no `-include` workaround |
| `isaac_ros_compression` | `fix/relocatable-nvbuf-dt-needed` | #2 | link three nvbuf libs by name (x86_64) + make `NVBUF_LIB_DIR` overridable (both arches) | **verified** — `recipes/ros-jazzy-isaac-ros-h264-decoder` builds from source with both patches and `DT_NEEDED` comes out clean |
| `isaac_ros_nitros` | `fix/epsilon-odr-inline` | #10 | `inline` on the `MachineEpsilon` specializations | **verified** — unblocks `nitros_detection3_d_array_type`, which would not link without it |
| `isaac_ros_nova` | `fix/license-tag-stray-quotes` | #4a | strip quotes from a `<license>` tag | trivial, no build impact |
| `ros2/launch` (jazzy) | `backport/pycollect-makemodule-pytest8` | #9 | backport the pytest 8 hook signature from rolling | **verified** — reproduced with pytest 9.1.1 |
| `isaac_ros_common` | `fix/findcudatoolkit` | #12 | `find_package(CUDA)` → `find_package(CUDAToolkit)`, drop the `CMP0146 OLD` block | **verified** — `isaac_ros_common` and `gxf_isaac_gems` both build against a component-based CUDA 13.3 toolkit, where `find_package(CUDA)` fails with `Specify CUDA_TOOLKIT_ROOT_DIR` |

## Not prepared, deliberately

- **#4b, the three copyright-block licenses** — the intended license is genuinely
  ambiguous (both repos mix Apache-2.0 and the Isaac ROS license, and the top-level
  `LICENSE` is Apache). Guessing on NVIDIA's behalf would be worse than asking. The
  `isaac_ros_manipulation` fork is therefore unused.
- **#3, GXF's `urm.nvidia.com` URLs** — the natural place to document the
  `-D<dep>_ROOT` workaround is `README.md`, but the `gxf` repo states it is published
  under the NVIDIA Isaac ROS software license, which does not permit modification. Only
  the per-file Apache-2.0 `third_party/cmake/*.cmake` are modifiable, and switching
  those five URLs to public mirrors needs hashes we cannot verify without risking their
  build. Report, don't patch.
- **#5** — the ament-index path is in `isaac_ros_common`'s CMake install rules, which
  carry no per-file Apache header. NVIDIA's pen. Note this is narrower than it first
  looked: the package *declares* the Isaac ROS license, but two of its four `.cmake`
  files carry their own `SPDX-License-Identifier: Apache-2.0`, which is what made #12
  patchable. Check the file header, not just `package.xml`.
- **#6** — turned out not to be an upstream bug at all. Building `osrf/negotiated` from
  source installs `libnegotiated.so` into plain `lib/`; the multiarch subdirectory comes
  from NVIDIA's deb build configuration. Nothing to send to OSRF.

## A correction worth reading before reviewing #2

The first version of the `isaac_ros_compression` patch used
`set_property(TARGET ... PROPERTY IMPORTED_SONAME ...)`, which is the obvious CMake
knob. **It does not work.** Measured on a deliberately soname-less library, the
`DT_NEEDED` entry stayed absolute whether the property was set or not — because the
library is still handed to the linker as an absolute path.

What does work is changing *how* the library is linked:

```
absolute path on the link line        -> DT_NEEDED /abs/path/libfoo.so
-L<dir> -l:libfoo.so                  -> DT_NEEDED libfoo.so
absolute path, library HAS a soname   -> DT_NEEDED libfoo.so
```

The branch was rewritten accordingly and the replacement was verified against a
replica of the real CMake structure, including the aarch64 fallback path.

## Verification status

**#1 is verified.** `ros-jazzy-isaac-ros-nitros` now applies the same one-line change
when it repacks the header (see `POST_FIXUP` in `scripts/gen_repack.py`), and
`ros-jazzy-isaac-ros-visual-slam` builds against it with the `-include cstdint`
workaround removed:

```
[10/12] Building CXX object CMakeFiles/visual_slam_node.dir/src/visual_slam_node.cpp.o
[11/12] Linking CXX shared library libvisual_slam_node.so
[12/12] Linking CXX executable isaac_ros_visual_slam
PASS: all dependencies resolve inside the prefix, no host Boost
```

So the upstream patch is exactly the change needed — no compensating flags anywhere.

**#2 is verified.** `recipes/ros-jazzy-isaac-ros-h264-decoder` is now a source build that
applies both patches from this branch, so building the package exercises the PR:

```
== DT_NEEDED ==
    libv4l2.so.0
    libnvbufsurface.so
    libnvbufsurftransform.so
PASS: no absolute paths in DT_NEEDED -- relocatable without binary editing
```

That replaced a repack which had to rewrite `DT_NEEDED` strings inside NVIDIA's
`libdecoder_node.so`. The byte-patching phase has been deleted from
`scripts/gen_repack.py` — the decoder was the only thing it ever fixed.

The branch grew a second commit while doing this: `NVBUF_LIB_DIR` was hardcoded, so a
conda build could not point at its own `nvv4l2`. Making it overridable is useful to any
packager off the FHS layout, and unlike the first commit it covers both architectures,
since substituting a variable for a literal path cannot change which file is found.

The end-to-end NVDEC *run* still needs a working GPU.

## Layout

```
isaac_ros_nitros/         fork, branch fix/cuvslam2-missing-cstdint
isaac_ros_compression/    fork, branch fix/relocatable-nvbuf-dt-needed
isaac_ros_nova/           fork, branch fix/license-tag-stray-quotes
isaac_ros_manipulation/   fork, unused (see #4b above)
gxf/                      fork, unused (see #3 above)
```

Each clone has `origin` pointing at the `wolfv` fork and `upstream` at
`NVIDIA-ISAAC-ROS`. Cloned with `GIT_LFS_SKIP_SMUDGE=1`, so the vendored GXF and
cuVSLAM blobs are pointers rather than ~600 MB of binaries.
