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
Standalone test runner for omni.ui tests.

Usage:
    python run_tests.py                    # run all tests
    python run_tests.py test_label         # run a specific module
    python run_tests.py -v                 # verbose output
    python run_tests.py -k test_general    # run tests matching a pattern

This script:
1. Sets up sys.path so ``import omni.ui`` resolves to the standalone build.
2. Initialises the standalone backend once.
3. Discovers and runs all ``test_*.py`` files in this directory via unittest.
"""

import os
import sys

# ---------------------------------------------------------------------------
# Path setup -- ensure the ovui package (omni.ui import namespace) is importable.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
_PYTHON_DIR = os.path.join(_REPO_ROOT, "python")

# Insert at front so our omni.ui takes precedence over any Kit install.
if _PYTHON_DIR not in sys.path:
    sys.path.insert(0, _PYTHON_DIR)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# ---------------------------------------------------------------------------
# Optional: set golden image directory from env or default.
# ---------------------------------------------------------------------------
GOLDEN_DIR = os.path.join(_SCRIPT_DIR, "golden")
os.environ.setdefault("OMNI_UI_GOLDEN_DIR", GOLDEN_DIR)


def main():
    """Entry point -- supports being invoked directly or via ``python -m``."""

    # Try pytest first (better output, -k support, etc.)
    try:
        import pytest
        args = [_SCRIPT_DIR, "-x", "--tb=short"]
        # Forward any CLI arguments
        args.extend(sys.argv[1:])
        sys.exit(pytest.main(args))
    except ImportError:
        pass

    # Fallback: plain unittest discovery
    import unittest

    loader = unittest.TestLoader()
    argv = sys.argv[1:]

    # If a specific module name is given (no leading dash), load only that.
    if argv and not argv[0].startswith("-"):
        module_name = argv[0]
        if not module_name.startswith("test_"):
            module_name = f"test_{module_name}"
        suite = loader.loadTestsFromName(module_name)
    else:
        suite = loader.discover(_SCRIPT_DIR, pattern="test_*.py")

    verbosity = 2 if "-v" in argv else 1
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
