#!/usr/bin/env python3
"""Rewrite absolute RUNPATHs in a conda prefix to $ORIGIN-relative paths.

The Isaac ROS debs are built for /opt/ros/jazzy with hard-coded RUNPATHs. Their
directory layout is preserved verbatim under $PREFIX, so every absolute entry can
be re-expressed relative to the shared object's own location:

    /opt/ros/jazzy/lib                       -> $ORIGIN/<up>/lib
    /opt/ros/jazzy/share/<pkg>/gxf/lib/std   -> $ORIGIN/<up>/share/<pkg>/gxf/lib/std
    /usr/local/cuda/lib64                    -> $ORIGIN/<up>/lib   (conda flattens CUDA)
    /opt/nvidia/vpi4/lib/x86_64-linux-gnu    -> $ORIGIN/<up>/lib

where <up> is the number of ".." hops from the file's directory back to $PREFIX.
Doing this at build time means no LD_LIBRARY_PATH activation hook is needed.
"""

import os
import subprocess
import sys

PREFIX = os.path.realpath(sys.argv[1])

# Absolute prefixes that should collapse onto $PREFIX/lib.
TO_LIB = ("/usr/local/cuda/lib64", "/usr/local/cuda/targets/x86_64-linux/lib",
          "/usr/lib/x86_64-linux-gnu", "/usr/lib64", "/usr/lib", "/lib64")
ROS_ROOT = "/opt/ros/jazzy"


def is_elf(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == b"\x7fELF"
    except OSError:
        return False


def runpath(path: str) -> str:
    out = subprocess.run(["patchelf", "--print-rpath", path],
                         capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ""


def rewrite(entries: list[str], up: str) -> list[str]:
    origin = "$ORIGIN" if not up else f"$ORIGIN/{up}"
    out = []
    for e in entries:
        if not e:
            continue
        # GXF core is built with Bazel, so its RUNPATHs are littered with
        # $ORIGIN/../../_solib_k8/... and $ORIGIN/libfoo.so.runfiles/... entries
        # pointing into a Bazel output tree that does not ship. Drop them: they
        # are dead weight and make real problems hard to read.
        if "_solib_" in e or ".runfiles" in e:
            continue
        if e.startswith("$ORIGIN"):
            new = e
        elif e == ROS_ROOT or e.startswith(ROS_ROOT + "/"):
            rel = e[len(ROS_ROOT):].lstrip("/")
            new = f"{origin}/{rel}" if rel else origin
        elif any(e == p or e.startswith(p + "/") for p in TO_LIB):
            new = f"{origin}/lib"
        elif e.startswith("/opt/nvidia/"):
            new = f"{origin}/lib"
        else:
            # Unknown absolute path: drop it rather than leak a host directory
            # into the package.
            continue
        if new and new not in out:
            out.append(new)
    # Always be able to find siblings in $PREFIX/lib.
    for fallback in (origin, f"{origin}/lib"):
        if fallback not in out:
            out.append(fallback)
    return out


def link_gxf_into_lib() -> int:
    """Symlink GXF shared objects from share/**/gxf/lib** into $PREFIX/lib.

    GXF extensions must stay under share/<pkg>/gxf/lib because NITROS loads them
    by path from the ament resource index. But the dynamic linker also has to
    resolve them as NEEDED entries across package boundaries, and a package being
    built cannot know where a sibling package will put its libraries. Symlinking
    into the one directory every consumer already has on its RPATH ($PREFIX/lib)
    solves that without duplicating ~20 MB of binaries.
    """
    libdir = os.path.join(PREFIX, "lib")
    os.makedirs(libdir, exist_ok=True)
    linked = 0
    share = os.path.join(PREFIX, "share")
    for dirpath, _dirnames, filenames in os.walk(share):
        if f"{os.sep}gxf{os.sep}lib" not in dirpath:
            continue
        for name in filenames:
            if ".so" not in name:
                continue
            src = os.path.join(dirpath, name)
            if not is_elf(src):
                continue
            dst = os.path.join(libdir, name)
            if os.path.exists(dst) or os.path.islink(dst):
                continue
            os.symlink(os.path.relpath(src, libdir), dst)
            linked += 1
    if linked:
        print(f"symlinked {linked} GXF libraries into lib/")
    return linked


def main() -> None:
    changed = 0
    for dirpath, _dirnames, filenames in os.walk(PREFIX):
        for name in filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path) or not is_elf(path):
                continue
            old = runpath(path)
            rel = os.path.relpath(dirpath, PREFIX)
            depth = 0 if rel == "." else len(rel.split(os.sep))
            up = "/".join([".."] * depth)
            new = ":".join(rewrite(old.split(":") if old else [], up))
            if new != old:
                subprocess.run(["patchelf", "--set-rpath", new, path], check=True)
                changed += 1
                print(f"    {os.path.relpath(path, PREFIX)}")
                if old:
                    print(f"        was: {old}")
                print(f"        now: {new}")
    print(f"relinked {changed} binaries")

    link_gxf_into_lib()


if __name__ == "__main__":
    main()
