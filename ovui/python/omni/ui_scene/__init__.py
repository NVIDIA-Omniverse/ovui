# SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
omni.ui.scene standalone
------------------------

3D scene overlay for omni.ui — geometric primitives, labels, images,
gesture recognition, and manipulators rendered into an ImGui draw list.
"""

# On Windows, _scene.pyd depends on ovui.dll (sibling omni/ui dir) and
# omni.ui.scene.dll (next to the .pyd). Register both directories with the DLL
# loader so `from omni.ui_scene import scene` works when it is the first
# import of the package (no-op on other platforms). omni.ui does the same
# for its own imports, but we cannot rely on the user having imported it.
import sys as _sys
import os as _os
if _sys.platform == "win32" and hasattr(_os, "add_dll_directory"):
    _pkg_dir = _os.path.dirname(_os.path.abspath(__file__))
    _os.add_dll_directory(_pkg_dir)
    _ui_dir = _os.path.join(_os.path.dirname(_pkg_dir), "ui")
    if _os.path.isdir(_ui_dir):
        _os.add_dll_directory(_ui_dir)
    # omniui_standalone.dll (loaded by omni.ui) links against the CUDA
    # runtime, which lives in the CUDA Toolkit bin dir and is not usually on
    # PATH. Pick it up from the usual env vars if set.
    for _cuda_env in ("CUDA_PATH", "CUDAToolkit_ROOT", "CUDA_HOME"):
        _cuda_root = _os.environ.get(_cuda_env)
        if _cuda_root:
            _cuda_bin = _os.path.join(_cuda_root, "bin")
            if _os.path.isdir(_cuda_bin):
                _os.add_dll_directory(_cuda_bin)
                break

from ._scene import *
from .gesture_bindings import GestureBinding, GestureBindings, GestureBindingManipulator
