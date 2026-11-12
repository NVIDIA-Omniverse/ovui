#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Run the native GPU upload tests on a computer with an NVIDIA GPU:
#   - byte_image_gpu_status_test: upload results on a real Vulkan + CUDA device;
#   - ovui/tests/test_native_frame_pacing_upload.py: native frame pacing with
#     the fake frame source;
#   - ovui/tests/test_byte_image_upload_status.py: upload results from Python.
# The runner exists to run them, so a skipped test fails the run: a skip there
# hides a broken setup.
#
# Usage: run_native_gpu_tests.sh <folder from collect_native_gpu_tests.sh> <python with ovui installed>
# Run it from the root of the repository.
set -euo pipefail

tests=$(cd "${1:?usage: run_native_gpu_tests.sh <tests folder> <python>}" && pwd)
python=${2:?usage: run_native_gpu_tests.sh <tests folder> <python>}

nvidia-smi -L
export OMNIUI_HEADLESS=1

echo "=== byte_image_gpu_status_test"
chmod +x "$tests/byte_image_gpu_status_test"
LD_LIBRARY_PATH="$tests${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$tests/byte_image_gpu_status_test"

echo "=== native frame pacing and upload result tests"
log=$(mktemp)
set +e
OMNIUI_FAKE_FRAME_SOURCE="$tests/libomniui_fake_frame_source.so" \
    "$python" -m pytest -c ovui/pyproject.toml -rs -p no:cacheprovider --timeout=600 \
    ovui/tests/test_native_frame_pacing_upload.py ovui/tests/test_byte_image_upload_status.py 2>&1 | tee "$log"
status=${PIPESTATUS[0]}
set -e
if [ "$status" -ne 0 ]; then
    echo "ERROR: the tests failed (pytest exit status $status)" >&2
    exit "$status"
fi
if grep -q '^SKIPPED' "$log"; then
    echo "ERROR: a test was skipped on the GPU runner; see the SKIPPED lines above" >&2
    exit 1
fi
echo "All native GPU upload tests ran and passed."
