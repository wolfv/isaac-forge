# Recipes for conda-forge

Packages that belong in conda-forge rather than in this project's channel: general
OSS libraries that Isaac ROS happens to need, built from source.

## v4l-utils — ready to submit

conda-forge has **no Video4Linux package at all**, which blocks anything needing
libv4l2 — including NVIDIA's NVDEC path, whose `nvv4l2` package is a libv4l2 plugin
(`Depends: libv4l-dev`, no `Provides`/`Conflicts`).

Built from source with meson, two outputs following the split convention:

| output | contents |
|---|---|
| `libv4l` | `libv4l1`, `libv4l2`, `libv4lconvert`, headers, pkg-config |
| `v4l-utils` | CLI tools (`v4l2-ctl`, `v4l2-compliance`, …) |

Verified locally — both outputs build and all tests pass:

```
libv4l2 linked and callable
v4l2-ctl 1.32.0
```

The test is a real link-and-call against `libv4l2` via pkg-config, not just a file
check, so a broken pkg-config or missing symbol fails the build.

Two things a reviewer will want to know:

- **Qt GUIs and DVB are disabled** (`qv4l2`, `qvidcap`, `libdvbv5`, `v4l2-tracer`,
  `bpf`, `gconv`). They would pull qt6 and a large tree for tools nobody has asked
  for. Easy to enable in the feedstock later.
- **`udevdir` and `sysconfdir` are redirected into the prefix.** `ir-keytable`
  installs its `rc_keymaps` under `udevdir`, which defaults to an absolute
  `/lib/udev` and fails with `EACCES` in any build sandbox. The keymaps are only read
  by `ir-keytable` itself, so keeping them in the prefix is harmless.

This project builds the same recipe into its own channel in the meantime, so switching
to the conda-forge package later is just a channel change.

## CV-CUDA — nothing to submit

Already in conda-forge, and it works: `libcvcuda` 0.16.0 has a **cuda130** build and
`libcvcuda-dev` carries the headers.

Worth recording why using it is safe despite Isaac being built against NVIDIA's 0.14:

- soname matches — both are `libcvcuda.so.0` / `libnvcv_types.so.0`
- the symbol version nodes are **identical**: `NVCV_0.0 0.2 0.3 0.4 0.5` in both
- every cvcuda/nvcv symbol the repacked Isaac binaries need resolves against 0.16
  (measured: 1 needed, 1 resolved), and `libnvcv_types.so.0` loads from it

So this project depends on conda-forge's `libcvcuda` / `libcvcuda-dev` directly and no
longer repacks NVIDIA's 0.14. Note that the CUDA 13 build only appears if the
environment pins `cuda-version 13.*`; without it the solver picks `cuda129`.
