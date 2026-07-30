#!/usr/bin/env python3
"""Rewrite absolute RUNPATHs in a conda prefix to $ORIGIN-relative paths.

Same job as the relink.py that scripts/gen_repack.py emits, with one rule added -- see
sibling_lib_dirs() below. Kept as its own copy rather than shared because this recipe is
hand-written; if the generated version grows the same rule, they should be reconciled.

The Isaac ROS debs are built for /opt/ros/jazzy with hard-coded RUNPATHs. Their directory
layout is preserved verbatim under $PREFIX, so every absolute entry can be re-expressed
relative to the binary's own location:

    /opt/ros/jazzy/lib        -> $ORIGIN/<up>/lib
    /usr/local/cuda/lib64     -> $ORIGIN/<up>/lib   (conda flattens CUDA)
    /cuvslam/build/bin        -> dropped; it is a path inside NVIDIA's build container

where <up> is the number of ".." hops from the file's directory back to $PREFIX. Doing
this at build time means no LD_LIBRARY_PATH activation hook is needed.
"""

import os
import subprocess
import sys

PREFIX = os.path.realpath(sys.argv[1])

# Absolute prefixes that should collapse onto $PREFIX/lib.
TO_LIB = ("/usr/local/cuda/lib64", "/usr/local/cuda/targets/x86_64-linux/lib",
          "/usr/lib/x86_64-linux-gnu", "/usr/lib64", "/usr/lib", "/lib64", "/lib")
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


def sibling_lib_dirs(dirpath: str) -> list[str]:
    """$ORIGIN-relative entries for shared objects in a sibling directory.

    isaac_ros_visual_mapping vendors cuVSLAM as a self-contained bundle:

        lib/isaac_ros_visual_mapping/visual_mapping/bin/cuvslam_api_launcher
        lib/isaac_ros_visual_mapping/visual_mapping/lib/libcuvslam.so

    The launcher NEEDs libcuvslam.so, which is neither beside it nor in $PREFIX/lib, so
    the generic $ORIGIN and $ORIGIN/<up>/lib fallbacks both miss it and the binary fails
    at dlopen with nothing earlier going wrong. Its shipped RUNPATH is /cuvslam/build/bin,
    a directory inside NVIDIA's build container, which cannot be mapped onto anything.

    Rather than special-case that one file, look for shared objects one level across --
    ../lib, ../lib64 -- and add the ones that exist. That is a property of the layout, so
    it keeps working if the bundle moves or another one appears.
    """
    out = []
    parent = os.path.dirname(dirpath)
    for name in ("lib", "lib64"):
        cand = os.path.join(parent, name)
        if cand == dirpath or not os.path.isdir(cand):
            continue
        if any(".so" in f for f in os.listdir(cand)):
            out.append(f"$ORIGIN/../{name}")
    return out


def rewrite(entries: list[str], up: str) -> list[str]:
    origin = "$ORIGIN" if not up else f"$ORIGIN/{up}"
    out = []
    for e in entries:
        if not e:
            # An empty RUNPATH entry means the current working directory. The Isaac tools
            # all ship ":/lib", so this is the common case, and keeping it would make what
            # a binary links against depend on where it was started from.
            continue
        if "_solib_" in e or ".runfiles" in e:
            # Bazel output-tree leftovers; they do not ship.
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
            # Unknown absolute path -- drop it rather than leak a build-machine directory
            # into the package. /cuvslam/build/bin lands here.
            continue
        if new and new not in out:
            out.append(new)
    # Always be able to find siblings, $PREFIX/lib, and a vendored bundle's lib dir.
    for fallback in (origin, f"{origin}/lib"):
        if fallback not in out:
            out.append(fallback)
    return out


def main() -> None:
    changed = 0
    for dirpath, _dirnames, filenames in os.walk(PREFIX):
        extra = sibling_lib_dirs(dirpath)
        for name in filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path) or not is_elf(path):
                continue
            old = runpath(path)
            rel = os.path.relpath(dirpath, PREFIX)
            depth = 0 if rel == "." else len(rel.split(os.sep))
            up = "/".join([".."] * depth)
            entries = rewrite(old.split(":") if old else [], up)
            for e in extra:
                if e not in entries:
                    entries.append(e)
            new = ":".join(entries)
            if new != old:
                subprocess.run(["patchelf", "--set-rpath", new, path], check=True)
                changed += 1
                print(f"    {os.path.relpath(path, PREFIX)}")
                if old:
                    print(f"        was: {old}")
                print(f"        now: {new}")
    print(f"relinked {changed} binaries")


if __name__ == "__main__":
    main()
