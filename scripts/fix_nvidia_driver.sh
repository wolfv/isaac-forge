#!/usr/bin/env bash
# Purge the mixed fc39/fc41 NVIDIA packages, install RPM Fusion's fc43 580,
# build the module, print the version. Run: sudo ./scripts/fix_nvidia_driver.sh
set -eu

dnf config-manager setopt cuda-fedora39-x86_64.enabled=0 cuda-fedora41-x86_64.enabled=0

# Every installed nvidia package except the Fedora-provided firmware. Includes
# libnvidia-ml / libnvidia-cfg / libnvidia-fbc / libnvidia-gpucomp, which do not
# match a "nvidia-*" prefix and caused the file conflicts.
mapfile -t OLD < <(rpm -qa --qf '%{name}\n' \
  | grep -i nvidia \
  | grep -v '^nvidia-gpu-firmware$' \
  | sort -u) || true

if [ "${#OLD[@]}" -gt 0 ]; then
  printf 'removing: %s\n' "${OLD[*]}"
  dnf remove -y --noautoremove "${OLD[@]}"
fi

dnf install -y --refresh akmod-nvidia xorg-x11-drv-nvidia xorg-x11-drv-nvidia-cuda

akmods --force
depmod -a

# If this prints 580.x the module built and you can reboot. If it errors, don't.
modinfo -F version nvidia
