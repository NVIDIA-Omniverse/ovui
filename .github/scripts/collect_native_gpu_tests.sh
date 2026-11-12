#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Copy the native GPU test programs of an ovui wheel build, and the shared
# libraries they load, into one folder. A GPU runner runs them from there with
# run_native_gpu_tests.sh. The programs find the libraries next to themselves
# (RUNPATH $ORIGIN).
#
# Usage: collect_native_gpu_tests.sh <ovui build folder, e.g. ovui/build/pip> <output folder>
set -euo pipefail

build=${1:?usage: collect_native_gpu_tests.sh <ovui build folder> <output folder>}
out=${2:?usage: collect_native_gpu_tests.sh <ovui build folder> <output folder>}
mkdir -p "$out"

copy() {
    local found=0
    for file in "$@"; do
        if [ -e "$file" ]; then
            # Copy the files that links point at: an artifact keeps no links.
            cp -L "$file" "$out/"
            found=1
        fi
    done
    if [ "$found" = 0 ]; then
        echo "ERROR: none of these files was built: $*" >&2
        exit 1
    fi
}

# The programs: the real Vulkan + CUDA upload test, and the fake frame source
# that the native frame pacing tests load.
copy "$build/standalone/byte_image_gpu_status_test"
copy "$build/standalone/libomniui_fake_frame_source.so"
# The ovui libraries they link.
copy "$build"/standalone/libomniui_standalone.so*
copy "$build/core/libomni.ui.so"
copy "$build/third_party/libovui_imgui.so"
# The CUDA runtime that the build linked; the GPU runner may not have it.
cudart=$(ldd "$build/standalone/byte_image_gpu_status_test" | awk '/libcudart\.so/ {print $3; exit}')
if [ -z "$cudart" ] || [ ! -e "$cudart" ]; then
    echo "ERROR: the CUDA runtime of byte_image_gpu_status_test was not found" >&2
    exit 1
fi
cp -L "$cudart" "$out/$(basename "$cudart")"

echo "Collected native GPU tests in $out:"
ls -l "$out"
