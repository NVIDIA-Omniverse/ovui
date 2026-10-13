# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Load ovui's ImGui library before a module that bundles its own is imported.

A process has one library named imgui (``imgui.dll`` / ``libimgui.so``).
ovui's copy also provides the old entry points ovrtx imports, but ovrtx's
older copy lacks what ``omni.ui`` needs. When ovrtx loads first, a later
``import omni.ui`` fails (Windows: "DLL load failed while importing
_standalone: The specified procedure could not be found"; Linux: "undefined
symbol: _ZN10ImDrawListD1Ev").

``ovui_imgui_preload.pth`` imports this module at interpreter startup. It only
adds an import finder, which loads ovui's ImGui library the first time one of
the trigger modules is imported, and then removes itself. It never imports
``omni.ui``.

The default trigger is ``ovrtx``, the renderer ovui itself is built against.
Any other package that bundles an older imgui adds its own module name --
either through ``OVUI_IMGUI_PRELOAD_MODULES`` (a path-separator or
comma-separated list read at interpreter startup) or, when it controls its own
import, by loading ovui's library first the way
``ovui_data_adapters.common.ovrtx_import`` does. ovui names no package but the
renderer it builds against.
"""

import os
import sys

_DEFAULT_TRIGGERS = ("ovrtx",)
_TRIGGER_ENV_VAR = "OVUI_IMGUI_PRELOAD_MODULES"
_LIBRARY = {"win32": "imgui.dll", "darwin": "libimgui.dylib"}.get(sys.platform, "libimgui.so")
_handle = None


def _triggers() -> frozenset:
    names = set(_DEFAULT_TRIGGERS)
    raw = os.environ.get(_TRIGGER_ENV_VAR, "")
    for chunk in raw.replace(os.pathsep, ",").split(","):
        name = chunk.strip()
        if name:
            names.add(name)
    return frozenset(names)


_TRIGGERS = _triggers()


def _load() -> None:
    global _handle
    import ctypes

    library = os.path.join(os.path.dirname(os.path.abspath(__file__)), "omni", "ui", _LIBRARY)
    if _handle is None and os.path.isfile(library):
        try:
            _handle = ctypes.CDLL(library)
        except OSError:
            pass


class _ImguiPreloadFinder:
    """Meta-path finder that only reacts to the first trigger-module import."""

    @classmethod
    def find_spec(cls, name, path=None, target=None):
        if name in _TRIGGERS:
            if cls in sys.meta_path:
                sys.meta_path.remove(cls)
            _load()
        return None


if not _TRIGGERS.intersection(sys.modules):
    sys.meta_path.insert(0, _ImguiPreloadFinder)
