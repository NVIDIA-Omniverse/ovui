#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Prepares an Ubuntu 22.04 x86_64 host to cross-compile the Linux ARM64 ovui
# wheels with ovui/cmake/toolchains/linux-aarch64.cmake:
#
#   * Ubuntu's aarch64-linux-gnu GCC (GCC 11, the native ARM64 runner's compiler)
#   * the CUDA sbsa cross runtime (cudart, driver stub) inside the host toolkit
#   * an ARM64 sysroot from ports.ubuntu.com holding the -dev packages the
#     native ARM64 build installs, plus their dependencies (glibc 2.35)
#   * the ARM64 build of the host Python's exact version, from the same
#     actions/python-versions release setup-python installs on ARM64 runners
#   * a "cross python": the host interpreter, reporting the ARM64 build's
#     platform, EXT_SUFFIX and SOABI, so setup.py, pybind11 and bdist_wheel
#     produce linux_aarch64 wheels with aarch64 extension names
#
# Usage: setup_linux_aarch64_cross.sh <cross-root>
#
# Needs sudo for apt, the host Python as `python` (or $PYTHON), and
# CUDAToolkit_ROOT naming the host CUDA toolkit (e.g. /usr/local/cuda-12.8).
# Writes OVUI_AARCH64_SYSROOT, OVUI_CROSS_PYTHON and OVUI_CROSS_CMAKE_ARGS to
# $GITHUB_ENV when set, and prints them as shell exports.
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <cross-root>" >&2
  exit 2
fi
mkdir -p "$1"
root="$(cd "$1" && pwd)"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python="${PYTHON:-python}"
cuda_root="${CUDAToolkit_ROOT:?CUDAToolkit_ROOT must name the host CUDA toolkit}"
cuda_version="$(basename "$cuda_root")"
cuda_version="${cuda_version#cuda-}"
cuda_version="${cuda_version//./-}"

# The build-time -dev packages the native ARM64 jobs installed (build-wheel.yml
# used a subset); runtime-only packages are not needed. apt adds dependencies.
sysroot_packages=(
  libc6-dev
  libstdc++-11-dev
  libvulkan-dev
  libegl1-mesa-dev
  libgl1-mesa-dev
  libwayland-dev
  wayland-protocols
  libxkbcommon-dev
  libx11-dev
  libxrandr-dev
  libxinerama-dev
  libxcursor-dev
  libxi-dev
)

echo "=== Host cross compiler and CUDA ${cuda_version} sbsa cross runtime ==="
echo "deb [signed-by=/usr/share/keyrings/cuda-archive-keyring.gpg] https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/cross-linux-sbsa/ /" \
  | sudo tee /etc/apt/sources.list.d/cuda-ubuntu2204-cross-linux-sbsa.list >/dev/null
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  g++-aarch64-linux-gnu \
  libwayland-bin \
  pkg-config \
  "cuda-cudart-cross-sbsa-${cuda_version}" \
  "cuda-driver-cross-sbsa-${cuda_version}"
test -f "$cuda_root/targets/sbsa-linux/lib/libcudart.so"
test -f "$cuda_root/targets/sbsa-linux/lib/stubs/libcuda.so"

echo "=== ARM64 sysroot ==="
# A private apt state: the host's apt configuration and dpkg database stay untouched.
apt_root="$root/apt"
sysroot="$root/sysroot"
rm -rf "$apt_root" "$sysroot"
mkdir -p "$apt_root/etc/apt/apt.conf.d" "$apt_root/etc/apt/preferences.d" \
  "$apt_root/var/lib/apt/lists/partial" "$apt_root/var/cache/apt/archives/partial" \
  "$apt_root/var/lib/dpkg"
touch "$apt_root/var/lib/dpkg/status"
ports="deb [arch=arm64 signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] http://ports.ubuntu.com/ubuntu-ports"
printf '%s\n' \
  "$ports jammy main universe" \
  "$ports jammy-updates main universe" \
  "$ports jammy-security main universe" \
  > "$apt_root/etc/apt/sources.list"
cat > "$apt_root/apt.conf" <<EOF
Dir "$apt_root/";
Dir::State::status "$apt_root/var/lib/dpkg/status";
APT::Architecture "arm64";
APT::Architectures { "arm64"; };
Debug::NoLocking "true";
APT::Sandbox::User "$(id -un)";
EOF
APT_CONFIG="$apt_root/apt.conf" apt-get update -qq
APT_CONFIG="$apt_root/apt.conf" apt-get install -y -qq --download-only --no-install-recommends "${sysroot_packages[@]}"

# Merged /usr, as on the runner, then unpack every downloaded package.
mkdir -p "$sysroot/usr/lib" "$sysroot/usr/bin" "$sysroot/usr/sbin"
ln -s usr/lib "$sysroot/lib"
ln -s usr/bin "$sysroot/bin"
ln -s usr/sbin "$sysroot/sbin"
for deb in "$apt_root"/var/cache/apt/archives/*.deb; do
  dpkg-deb -x "$deb" "$sysroot"
done
# Absolute links would point into the host; make them sysroot-relative.
find "$sysroot" -type l -lname '/*' -print0 | while IFS= read -r -d '' link; do
  target="$(readlink "$link")"
  ln -sfn "$(realpath -m --relative-to="$(dirname "$link")" "$sysroot$target")" "$link"
done
dpkg-deb -f "$(ls "$apt_root"/var/cache/apt/archives/libc6_*.deb)" Package Version

echo "=== ARM64 Python matching the host Python ==="
py_version="$("$python" -c 'import platform; print(platform.python_version())')"
py_url="$("$python" - "$py_version" <<'PY'
import json
import sys
import urllib.request

manifest = "https://raw.githubusercontent.com/actions/python-versions/main/versions-manifest.json"
with urllib.request.urlopen(manifest) as response:
    releases = json.load(response)
for release in releases:
    if release["version"] != sys.argv[1]:
        continue
    for item in release["files"]:
        if (item["platform"], item.get("platform_version"), item["arch"]) == ("linux", "22.04", "arm64"):
            print(item["download_url"])
            raise SystemExit(0)
raise SystemExit(f"no linux 22.04 arm64 Python {sys.argv[1]} in {manifest}")
PY
)"
echo "$py_url"
target_python="$root/python"
rm -rf "$target_python"
mkdir -p "$target_python"
curl -fsSL "$py_url" | tar -xz -C "$target_python"
py_minor="${py_version%.*}"
target_include="$target_python/include/python$py_minor"
test -f "$target_include/pyconfig.h"
sysconfig_name="_sysconfigdata__linux_aarch64-linux-gnu"
mkdir -p "$root/sysconfig"
cp "$target_python/lib/python$py_minor/$sysconfig_name.py" "$root/sysconfig/"

cross_python="$root/bin/python"
mkdir -p "$root/bin"
cat > "$cross_python" <<EOF
#!/bin/sh
# The host Python, configured as the ARM64 Python $py_version for building wheels.
export _PYTHON_HOST_PLATFORM=linux-aarch64
export _PYTHON_SYSCONFIGDATA_NAME=$sysconfig_name
export PYTHONPATH="$root/sysconfig\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$(command -v "$python")" "\$@"
EOF
chmod +x "$cross_python"
"$cross_python" - <<'PY'
import sysconfig
assert sysconfig.get_platform() == "linux-aarch64", sysconfig.get_platform()
assert sysconfig.get_config_var("EXT_SUFFIX").endswith("-aarch64-linux-gnu.so"), sysconfig.get_config_var("EXT_SUFFIX")
print("cross python:", sysconfig.get_platform(), sysconfig.get_config_var("EXT_SUFFIX"))
PY

echo "=== ovui build requirements on the host Python ==="
# Cross builds run without build isolation: pip would resolve an isolated
# build environment for ARM64 and install tools the host cannot run.
"$python" - "$repo/ovui/pyproject.toml" <<'PY' > "$root/build-requirements.txt"
import sys
import tomllib

with open(sys.argv[1], "rb") as f:
    print("\n".join(tomllib.load(f)["build-system"]["requires"]))
PY
"$python" -m pip install -r "$root/build-requirements.txt"

cmake_args="-DCMAKE_TOOLCHAIN_FILE=$repo/ovui/cmake/toolchains/linux-aarch64.cmake"
cmake_args+=" -DPYTHON_INCLUDE_DIR=$target_include -DPython_INCLUDE_DIR=$target_include"
cmake_args+=" -DCUDAToolkit_ROOT=$cuda_root"
{
  echo "OVUI_AARCH64_SYSROOT=$sysroot"
  echo "OVUI_CROSS_PYTHON=$cross_python"
  echo "OVUI_CROSS_CMAKE_ARGS=$cmake_args"
} > "$root/cross.env"
if [ -n "${GITHUB_ENV:-}" ]; then
  cat "$root/cross.env" >> "$GITHUB_ENV"
fi
sed 's/^/export /; s/=\(.*\)$/="\1"/' "$root/cross.env"
