# SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""
ovui
----

ovui is Omniverse's UI toolkit for creating beautiful and flexible graphical user interfaces
in the Kit extensions. ovui provides the basic types necessary to create rich extensions with
a fluid and dynamic user interface in Omniverse Kit. It gives a layout system and includes
widgets for creating visual components, receiving user input, and creating data models. It allows
user interface components to be built around their behavior and enables a declarative flavor of
describing the layout of the application. ovui gives a very flexible styling system that
allows deep customizing the final look of the application.

The product/distribution is named ``ovui``; the Python import namespace remains ``omni.ui``.

Typical Example
---------------

Typical example to create a window with two buttons:

.. code-block::

    import omni.ui as ui

    _window_example = ui.Window("Example Window", width=300, height=300)

    with _window_example.frame:
        with ui.VStack():
            ui.Button("click me")

            def move_me(window):
                window.setPosition(200, 200)

            def size_me(window):
                window.width = 300
                window.height = 300

            ui.Button("Move to (200,200)", clicked_fn=lambda w=self._window_example: move_me(w))
            ui.Button("Set size (300,300)", clicked_fn=lambda w=self._window_example: size_me(w))

Detailed Documentation
----------------------

ovui is shipped with the developer documentation that is written with ovui. For detailed documentation, please
see `omni.example.ui` extension. It has detailed descriptions of all the classes, best practices, and real-world usage
examples.

Layout
------

* Arrangement of elements
    * :class:`omni.ui.CollapsableFrame`
    * :class:`omni.ui.Frame`
    * :class:`omni.ui.HStack`
    * :class:`omni.ui.Placer`
    * :class:`omni.ui.ScrollingFrame`
    * :class:`omni.ui.Spacer`
    * :class:`omni.ui.VStack`
    * :class:`omni.ui.ZStack`

* Lengths
    * :class:`omni.ui.Fraction`
    * :class:`omni.ui.Percent`
    * :class:`omni.ui.Pixel`

Widgets
-------

* Base Widgets
    * :class:`omni.ui.Button`
    * :class:`omni.ui.Image`
    * :class:`omni.ui.Label`

* Shapes
    * :class:`omni.ui.Circle`
    * :class:`omni.ui.Line`
    * :class:`omni.ui.Rectangle`
    * :class:`omni.ui.Triangle`

* Menu
    * :class:`omni.ui.Menu`
    * :class:`omni.ui.MenuItem`

* Model-View Widgets
    * :class:`omni.ui.AbstractItemModel`
    * :class:`omni.ui.AbstractValueModel`
    * :class:`omni.ui.CheckBox`
    * :class:`omni.ui.ColorWidget`
    * :class:`omni.ui.ComboBox`
    * :class:`omni.ui.RadioButton`
    * :class:`omni.ui.RadioCollection`
    * :class:`omni.ui.TreeView`

* Model-View Fields
    * :class:`omni.ui.FloatField`
    * :class:`omni.ui.IntField`
    * :class:`omni.ui.MultiField`
    * :class:`omni.ui.StringField`

* Model-View Drags and Sliders
    * :class:`omni.ui.FloatDrag`
    * :class:`omni.ui.FloatSlider`
    * :class:`omni.ui.IntDrag`
    * :class:`omni.ui.IntSlider`

* Model-View ProgressBar
    * :class:`omni.ui.ProgressBar`

* Windows
    * :class:`omni.ui.ToolBar`
    * :class:`omni.ui.Window`
    * :class:`omni.ui.Workspace`

* Web
    * :class:`omni.ui.WebViewWidget`

"""

# Build provenance — populated by setup.py at build time. The fallback values
# only apply when the package was imported without ever having been built
# (e.g. running directly from a source tree without `pip install`).
try:
    from ._build_info import __version__, __commit__
except ImportError:  # pragma: no cover - source-tree import without build
    __version__ = "0.0.0+unknown"
    __commit__ = "unknown"

# On Windows, ensure the package directory is in the DLL search path so that
# ovui.dll and the backend library (next to the .pyd) can be found.
import sys as _sys
import os as _os
if _sys.platform == "win32" and hasattr(_os, "add_dll_directory"):
    _pkg_dir = _os.path.dirname(_os.path.abspath(__file__))
    _os.add_dll_directory(_pkg_dir)
    # omniui_standalone.dll depends on ovuiscene.dll, which lives in the
    # sibling omni/ui_scene/ package directory.
    _scene_dir = _os.path.join(_os.path.dirname(_pkg_dir), "ui_scene")
    if _os.path.isdir(_scene_dir):
        _os.add_dll_directory(_scene_dir)
    # CUDA runtime (cudart64_XXX.dll) lives in the toolkit's bin dir, which
    # is not usually on PATH. Pick it up from the usual env vars if set.
    for _cuda_env in ("CUDA_PATH", "CUDAToolkit_ROOT", "CUDA_HOME"):
        _cuda_root = _os.environ.get(_cuda_env)
        if _cuda_root:
            _cuda_bin = _os.path.join(_cuda_root, "bin")
            if _os.path.isdir(_cuda_bin):
                _os.add_dll_directory(_cuda_bin)
                break

# Detect whether we are running inside Kit or standalone
from ._compat import _IN_KIT

# The browser WebAssembly build links `_ui` as a built-in CPython extension
# module. Register it under the package-qualified name before relative imports.
if _sys.platform == "emscripten":
    import importlib as _importlib
    _ui_module = _importlib.import_module("_ui")
    _sys.modules.setdefault(__name__ + "._ui", _ui_module)

# Importing TextureFormat here explicitly to maintain backwards compatibility
try:
    from omni.gpu_foundation_factory import TextureFormat, RpResource
except (ImportError, ModuleNotFoundError):
    # Standalone: pull TextureFormat from the pybind module if available,
    # provide a no-op placeholder for RpResource.
    try:
        from ._ui import TextureFormat
    except ImportError:
        pass

    class RpResource:  # noqa: E303 – intentional redefinition for standalone
        """Placeholder for RpResource when running outside Kit."""
        pass

from ._ui import *
from .color_utils import color
from .constant_utils import constant
from .markdown_styles import DEFAULT_MARKDOWN_STYLE, MARKDOWN_STYLE_NAMES
from .markdown_styles import markdown_background, markdown_style, markdown_theme
from .style_utils import style
from .url_utils import url

if _IN_KIT:
    from .workspace_utils import dump_workspace
    from .workspace_utils import restore_workspace
    from .workspace_utils import compare_workspace
    from .extension import UIPreferencesExtension
    from .internal_session_notification import InternalSessionNotificationExtension
    from .workspace_utils import CompareDelegate

def add_to_namespace(module=None, module_locals=locals()):
    class AutoRemove:
        def __init__(self):
            self.__key = module.__name__.split(".")[-1]
            module_locals[self.__key] = module

        def __del__(self):
            module_locals.pop(self.__key, None)

    if not module:
        return

    return AutoRemove()


if _IN_KIT:
    # Add the static methods to Workspace
    setattr(Workspace, "dump_workspace", dump_workspace)
    setattr(Workspace, "restore_workspace", restore_workspace)
    setattr(Workspace, "compare_workspace", compare_workspace)

    del dump_workspace
    del restore_workspace
    del compare_workspace


def set_shade(shade_name: str | None = None):
    color.set_shade(shade_name)
    constant.set_shade(shade_name)
    url.set_shade(shade_name)

def set_menu_delegate(delegate: MenuDelegate):
    """
    Set the default delegate to use it when the item doesn't have a
    delegate.
    """
    MenuDelegate.set_default_delegate(delegate)

# Browser CPython helpers -- only available in the wasm build. They are thin
# aliases over functions exported by the real pybind11 `_ui` module.
if _sys.platform == "emscripten":
    from . import _ui as _ui_module

    _web_init = _ui_module._web_init
    _web_tick = _ui_module._web_tick
    _web_shutdown = _ui_module._web_shutdown
    _web_reset = _ui_module._web_reset
    _web_set_canvas_size = _ui_module._web_set_canvas_size
    _web_window_callback_count = _ui_module._web_window_callback_count
    _web_backend_info = _ui_module._web_backend_info
    _web_font_info = _ui_module._web_font_info
    _web_dpi_info = _ui_module._web_dpi_info

    def init(
        title: str = "omni.ui",
        width: int = 1280,
        height: int = 640,
        *,
        canvas_selector: str = "#canvas",
        device_pixel_ratio: float = 1.0,
        **_kwargs,
    ):
        return _web_init(canvas_selector, width, height, device_pixel_ratio)

    def shutdown():
        return _web_shutdown()

    def reset():
        return _web_reset()

    def next_frame():
        return _web_tick()

    def run():
        raise RuntimeError("ui.run() is not used in the browser; requestAnimationFrame calls ui.next_frame().")

# Standalone helpers -- only available outside Kit
elif not _IN_KIT:
    from .standalone import (
        FrameInfo,
        get_max_frame_rate,
        init,
        next_frame,
        run,
        run_async,
        set_max_frame_rate,
        shutdown,
    )

# Kit-compatible import path: `from omni.ui import scene`. The first browser
# target intentionally ships ovui only, not omni.ui_scene.
if _sys.platform == "emscripten":
    scene = None
else:
    import omni.ui_scene as scene
