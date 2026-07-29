#!/usr/bin/env python3
"""Resolve the dependency closure of Isaac ROS debian packages.

Parses the Isaac ROS apt `Packages` index and walks `Depends:` to produce the
full closure for one or more target packages, split into:

  * isaac    -- packages provided by the Isaac ROS apt repo (we repack these)
  * external -- everything else (must come from RoboStack / conda-forge / Ubuntu)

Usage:
    python scripts/aptclosure.py <Packages-file> <pkg> [<pkg> ...]
    python scripts/aptclosure.py --urls <Packages-file> <pkg> [...]   # print download URLs
"""

from __future__ import annotations

import re
import sys

BASE = "https://isaac.download.nvidia.com/isaac-ros/release-4"

FIELD = re.compile(r"^([A-Za-z0-9-]+):\s*(.*)$", re.M)


def parse(path: str) -> dict[str, dict[str, str]]:
    text = open(path, encoding="utf-8", errors="replace").read()
    index: dict[str, dict[str, str]] = {}
    provides: dict[str, str] = {}
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        d = dict(FIELD.findall(block))
        name = d.get("Package")
        if not name:
            continue
        index[name] = d
        # Track Provides: so virtual names (libnvinfer.so.10, ...) resolve too.
        for prov in d.get("Provides", "").split(","):
            prov = prov.strip().split()[0] if prov.strip() else ""
            if prov:
                provides[prov] = name
    for virt, real in provides.items():
        index.setdefault(virt, index[real])
    return index


def deps_of(entry: dict[str, str]) -> list[str]:
    """Package names from Depends:, taking the first option of any alternation."""
    out = []
    for clause in entry.get("Depends", "").split(","):
        clause = clause.strip()
        if not clause:
            continue
        first = clause.split("|")[0].strip()
        name = first.split()[0] if first else ""
        if name:
            out.append(name)
    return out


def closure(index: dict, targets: list[str]) -> tuple[set[str], set[str]]:
    isaac: set[str] = set()
    external: set[str] = set()
    stack = list(targets)
    while stack:
        name = stack.pop()
        if name in isaac or name in external:
            continue
        entry = index.get(name)
        if entry is None:
            external.add(name)
            continue
        isaac.add(name)
        stack.extend(deps_of(entry))
    return isaac, external


def main() -> None:
    argv = sys.argv[1:]
    urls = False
    if argv and argv[0] == "--urls":
        urls, argv = True, argv[1:]
    if len(argv) < 2:
        sys.exit(__doc__)

    packages_file, targets = argv[0], argv[1:]
    index = parse(packages_file)
    isaac, external = closure(index, targets)

    if urls:
        for name in sorted(isaac):
            fn = index[name].get("Filename")
            if fn:
                print(f"{BASE}/{fn}")
        return

    print(f"targets: {', '.join(targets)}")
    print(f"\nfrom the Isaac apt repo ({len(isaac)}):")
    for name in sorted(isaac):
        print(f"  {name}  {index[name].get('Version','')}")
    print(f"\nexternal, must come from RoboStack/conda-forge/Ubuntu ({len(external)}):")
    for name in sorted(external):
        print(f"  {name}")


if __name__ == "__main__":
    main()
