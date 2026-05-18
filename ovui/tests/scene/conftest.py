# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""
conftest.py for scene tests.

Sets up sys.path so the ovui-bundled omni.ui / omni.ui_scene packages from
python/ are found before any system-installed versions.
"""
import sys
from pathlib import Path

_SCENE_DIR = Path(__file__).resolve().parent
_TESTS_DIR = _SCENE_DIR.parent
_REPO_ROOT = _TESTS_DIR.parent
_PYTHON_DIR = _REPO_ROOT / "python"

# Insert at the front so standalone takes precedence over site-packages.
for p in [str(_PYTHON_DIR), str(_TESTS_DIR), str(_SCENE_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# If omni.ui_scene was already imported (e.g., from a site-packages stub),
# evict it so the next import picks up the standalone version.
_stale = [k for k in list(sys.modules) if k == "omni.ui_scene" or k.startswith("omni.ui_scene.")]
for _k in _stale:
    del sys.modules[_k]
