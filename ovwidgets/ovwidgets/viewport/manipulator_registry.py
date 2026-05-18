# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ManipulatorRegistry — dispatcher for selection-driven gizmo placement.

Also hosts :class:`ToolRegistry`, which owns the active-tool setting for
:class:`~ovwidgets.viewport.transform_manipulator.TransformManipulator` and cycles
between translate / rotate / scale via the Maya / Blender-style ``W/E/R``
hotkeys (Step C.1 of the viewport behavior).

* :class:`ManipulatorRegistry` — predates Phase C; routes selection changes
  to a ``show``/``hide`` gizmo interface. Retained for now because Step C.5
  still has to subsume its centroid-computation behaviour into
  :class:`~ovwidgets.viewport.prim_transform_model.PrimTransformModel`.
* :class:`ToolRegistry` — Phase C.1 addition. Reads the
  ``viewport.manipulator.active_tool`` setting (default ``"translate"``),
  subscribes to setting changes, and converts ``W/E/R`` key events into
  tool updates on the attached :class:`TransformManipulator`.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional

from ovwidgets.viewport.transform_manipulator import (
    TOOL_ROTATE,
    TOOL_SCALE,
    TOOL_TRANSLATE,
    VALID_TOOLS,
)

# Setting key polled + subscribed to by :class:`ToolRegistry`. Matches the
# name called out in the viewport behavior
ACTIVE_TOOL_SETTING = "viewport.manipulator.active_tool"

# GLFW key codes for W / E / R. ``omni.ui`` surfaces the raw GLFW printable
# key code (uppercase ASCII) through ``Window.set_key_pressed_fn``; the
# ovui binding passes it straight through (see
# ``ovwidgets.viewport/camera_flight_keyboard.py`` for the equivalent convention
# on W/A/S/D/Q/E).
_KEY_W = ord("W")
_KEY_E = ord("E")
_KEY_R = ord("R")

# Mapping from hotkey to tool name. The ordering matches the Maya / Blender
# convention ``W → translate``, ``E → rotate``, ``R → scale``.
_KEY_TO_TOOL = {
    _KEY_W: TOOL_TRANSLATE,
    _KEY_E: TOOL_ROTATE,
    _KEY_R: TOOL_SCALE,
}

# All modifier bits we consider "modified" — if any are set when W/E/R is
# pressed, the event belongs to some other shortcut (Ctrl+R reload, etc.)
# and ToolRegistry ignores it. The bit values match
# ``omni.ui.kKeyMod*`` (see ``ovui/core/include/omni/ui/Types.h``).
_MOD_SHIFT = 1 << 0
_MOD_CTRL = 1 << 1
_MOD_ALT = 1 << 2
_ANY_MOD = _MOD_SHIFT | _MOD_CTRL | _MOD_ALT


class ManipulatorRegistry:
    """Central dispatcher: routes selection changes to the gizmo."""

    def __init__(self, scene_view: Any, transform_model: Any, transform_manip: Any) -> None:
        self._scene_view = scene_view
        self._model = transform_model
        self._manip = transform_manip

    def on_selection_changed(self, paths: List[str]) -> None:
        self._model.set_selection(paths)
        if not paths:
            self._manip.hide()
            return
        origins = []
        for path in paths:
            m = self._model._transform.get_world_transform(path)
            origins.append([m[3][0], m[3][1], m[3][2]])
        n = len(origins)
        cx = sum(o[0] for o in origins) / n
        cy = sum(o[1] for o in origins) / n
        cz = sum(o[2] for o in origins) / n
        self._manip.show([cx, cy, cz])


class ToolRegistry:
    """Owns the active transform-tool setting and the W/E/R hotkey contract.

    Two inputs flow in:

    * ``W`` / ``E`` / ``R`` key presses (forwarded from the application's
      key dispatcher via :meth:`handle_key_event`) — unmodified keys update
      the setting, modified keys are ignored so ``Ctrl+W`` (close window)
      and friends still reach their real handlers.
    * Setting mutations on ``viewport.manipulator.active_tool`` (from a UI
      toolbar, the settings dialog, or programmatic ``settings.set``) —
      delivered through the subscription registered in ``__init__``.

    One output flows out:

    * The attached :class:`~ovwidgets.viewport.transform_manipulator.TransformManipulator`
      has its ``tool`` property set, which in turn calls ``invalidate()`` so
      the next draw rebuilds the gizmo for the new tool.

    An optional ``on_tool_changed`` callback is fired for external listeners
    (status bar, analytics) — passed ``(old_tool, new_tool)``.

    The registry is resilient to ``settings`` / ``manipulator`` being ``None``
    so unit tests can exercise the key-dispatch path in isolation.
    """

    def __init__(
        self,
        settings: Any = None,
        manipulator: Any = None,
        on_tool_changed: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self._settings = settings
        self._manipulator = manipulator
        self._on_tool_changed = on_tool_changed
        # Seed from settings if available; otherwise fall back to the plan's
        # default (translate). Invalid values in the settings store are
        # coerced to the default so a corrupted JSON can't wedge the UI.
        initial = TOOL_TRANSLATE
        if settings is not None:
            raw = settings.get(ACTIVE_TOOL_SETTING, TOOL_TRANSLATE)
            if raw in VALID_TOOLS:
                initial = raw
            else:
                # Repair the setting so the dialog / next run agree with us.
                settings.set(ACTIVE_TOOL_SETTING, TOOL_TRANSLATE)
        self._active_tool: str = initial
        self._sub = None
        if settings is not None and hasattr(settings, "subscribe"):
            self._sub = settings.subscribe(
                ACTIVE_TOOL_SETTING, self._on_setting_changed
            )
        # Propagate the initial tool to the manipulator so setup order
        # (ToolRegistry first, then manipulator) doesn't matter.
        self._apply_to_manipulator()

    # -- introspection ----------------------------------------------------

    @property
    def active_tool(self) -> str:
        return self._active_tool

    def attach_manipulator(self, manipulator: Any) -> None:
        """Bind a manipulator after construction and push the current tool into it."""
        self._manipulator = manipulator
        self._apply_to_manipulator()

    # -- inputs -----------------------------------------------------------

    def handle_key_event(self, key: int, modifiers: int, pressed: bool) -> bool:
        """Interpret a keyboard event. Returns True iff it switched tools.

        Only *unmodified* key-*down* events for W/E/R switch tools.
        Modifier-carrying events (Ctrl+R etc.) and key-*up* events are ignored.
        """
        if not pressed:
            return False
        if modifiers & _ANY_MOD:
            return False
        tool = _KEY_TO_TOOL.get(key)
        if tool is None:
            return False
        self.set_active_tool(tool)
        return True

    def set_active_tool(self, tool: str) -> None:
        """Update the active tool, persist via settings, and rebuild the gizmo."""
        if tool not in VALID_TOOLS:
            raise ValueError(f"tool must be one of {VALID_TOOLS!r}, got {tool!r}")
        if tool == self._active_tool:
            return
        old = self._active_tool
        self._active_tool = tool
        # Write-through to settings if present — subscribers elsewhere
        # (toolbar, settings dialog) observe the change the same way.
        if self._settings is not None:
            self._settings.set(ACTIVE_TOOL_SETTING, tool)
        self._apply_to_manipulator()
        if self._on_tool_changed is not None:
            self._on_tool_changed(old, tool)

    def destroy(self) -> None:
        """Cancel the settings subscription. Safe to call more than once."""
        if self._sub is not None:
            self._sub.cancel()
            self._sub = None

    # -- internals --------------------------------------------------------

    def _on_setting_changed(self, _key: str, value: Any) -> None:
        if value not in VALID_TOOLS or value == self._active_tool:
            return
        old = self._active_tool
        self._active_tool = value
        self._apply_to_manipulator()
        if self._on_tool_changed is not None:
            self._on_tool_changed(old, value)

    def _apply_to_manipulator(self) -> None:
        if self._manipulator is None:
            return
        try:
            self._manipulator.tool = self._active_tool
        except Exception:
            # Fail-safe: a misbehaving manipulator should not take the
            # registry down. The next invalidate() will reapply.
            pass
