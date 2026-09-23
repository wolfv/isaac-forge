#!/usr/bin/env python3
"""Small regeneration check for the staged Lyrical source recipes."""

from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
subprocess.run(["python", str(root / "scripts/gen_lyrical.py"),
                "ros-lyrical-isaac-deploy-core", "ros-lyrical-isaac-ros-common"],
               cwd=root, check=True)
core = (root / "recipes-lyrical/ros-lyrical-isaac-ros-common/recipe.yaml").read_text()
deploy = (root / "recipes-lyrical/ros-lyrical-isaac-deploy-core/recipe.yaml").read_text()
assert "ros-lyrical-rclcpp" in core and "ros-jazzy-" not in core
assert "ros-lyrical-rcpputils" in deploy and "ros-lyrical-tl-expected" not in deploy
assert (root / "recipes-lyrical/ros-lyrical-isaac-ros-common/patches").is_dir()
assert not (root / "recipes-lyrical/ros-lyrical-rosidl-buffer/recipe.yaml").exists()

# Compare the *same* recipe with only channel_sources changed, not package names.
recipe = root / "recipes-lyrical/ros-lyrical-isaac-ros-common/recipe.yaml"
with tempfile.TemporaryDirectory() as tmp:
    jazzy = Path(tmp) / "jazzy.yaml"
    jazzy.write_text("channel_sources:\n  - ./output,https://prefix.dev/robostack-jazzy,conda-forge\n")
    hashes = []
    for channels in (root / "variants-lyrical.yaml", jazzy):
        rendered = subprocess.run(
            ["rattler-build", "build", "--recipe", str(recipe), "--render-only",
             "--target-platform", "linux-64", "-m", str(root / "variants.yaml"),
             "-m", str(channels)], cwd=root, check=True, capture_output=True, text=True)
        hashes.append(re.search(r'"hash": "([a-f0-9]+)"', rendered.stdout).group(1))
    assert hashes[0] != hashes[1], hashes
print("Lyrical source recipes and distinct channel variant hash: OK")
