#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""
Generate (or regenerate) golden images for all visual tests.

Usage::

    python tests/generate_golden.py            # all test files
    python tests/generate_golden.py test_label  # specific module

Sets ``OMNI_UI_GENERATE_GOLDEN=1`` so that ``finalize_test()`` overwrites
existing goldens with fresh captures.  For deterministic rendering the
script forces Mesa's software rasteriser (llvmpipe).
"""
import os
import subprocess
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

# Force golden generation mode
os.environ["OMNI_UI_GENERATE_GOLDEN"] = "1"

# Ensure a DISPLAY is set (Xvfb or similar)
os.environ.setdefault("DISPLAY", ":99.0")

# Use Mesa llvmpipe for reproducible software rendering
os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"

# Build pytest arguments
pytest_args = [
    sys.executable, "-m", "pytest",
    _TESTS_DIR,
    "-v", "--tb=short",
]

# Allow narrowing to specific test modules via CLI args
if len(sys.argv) > 1:
    # Replace the directory arg with specific files
    pytest_args = [
        sys.executable, "-m", "pytest",
        "-v", "--tb=short",
    ]
    for arg in sys.argv[1:]:
        path = os.path.join(_TESTS_DIR, arg if arg.endswith(".py") else f"{arg}.py")
        pytest_args.append(path)

sys.exit(subprocess.call(pytest_args))
