# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`ovwidgets.viewport.manipulator_registry.ToolRegistry`.

Covers Step C.1's W/E/R hotkey contract:

* Default tool is ``translate``.
* ``W`` / ``E`` / ``R`` key-down events cycle through translate / rotate / scale.
* Modifier-bearing events are ignored so ``Ctrl+W`` etc. stay with their
  real handlers.
* Key-*up* events are ignored (only presses switch).
* Setting mutations on ``viewport.manipulator.active_tool`` reach the
  registry and propagate to the attached manipulator.
* ``destroy()`` cancels the settings subscription.
* Corrupt setting values self-heal to ``translate``.
"""

from __future__ import annotations

from typing import List

import pytest

from ovwidgets.common.settings import Settings
from ovwidgets.viewport.manipulator_registry import (
    ACTIVE_TOOL_SETTING,
    ToolRegistry,
)
from ovwidgets.viewport.transform_manipulator import (
    TOOL_ROTATE,
    TOOL_SCALE,
    TOOL_TRANSLATE,
)

# -- helpers --------------------------------------------------------------


class _StubManipulator:
    """Captures ``tool`` assignments so tests can inspect propagation."""

    def __init__(self, initial: str = TOOL_TRANSLATE) -> None:
        self._tool = initial
        self.assignments: List[str] = []

    @property
    def tool(self) -> str:
        return self._tool

    @tool.setter
    def tool(self, value: str) -> None:
        self._tool = value
        self.assignments.append(value)


# -- defaults -------------------------------------------------------------


class TestDefaults:
    def test_no_settings_no_manip_default_translate(self):
        reg = ToolRegistry()
        assert reg.active_tool == TOOL_TRANSLATE

    def test_fresh_settings_returns_translate(self):
        reg = ToolRegistry(settings=Settings())
        assert reg.active_tool == TOOL_TRANSLATE

    def test_settings_preset_to_rotate(self):
        s = Settings()
        s.set(ACTIVE_TOOL_SETTING, TOOL_ROTATE)
        reg = ToolRegistry(settings=s)
        assert reg.active_tool == TOOL_ROTATE

    def test_corrupt_settings_self_heal_to_translate(self):
        s = Settings()
        s.set(ACTIVE_TOOL_SETTING, "nonsense")
        reg = ToolRegistry(settings=s)
        assert reg.active_tool == TOOL_TRANSLATE
        assert s.get(ACTIVE_TOOL_SETTING) == TOOL_TRANSLATE


# -- hotkey contract ------------------------------------------------------


class TestHotkeys:
    def _make(self):
        s = Settings()
        manip = _StubManipulator()
        reg = ToolRegistry(settings=s, manipulator=manip)
        return reg, manip, s

    def test_w_selects_translate(self):
        reg, manip, _ = self._make()
        reg.set_active_tool(TOOL_ROTATE)
        assert reg.handle_key_event(ord("W"), 0, True) is True
        assert reg.active_tool == TOOL_TRANSLATE
        assert manip.tool == TOOL_TRANSLATE

    def test_e_selects_rotate(self):
        reg, manip, _ = self._make()
        assert reg.handle_key_event(ord("E"), 0, True) is True
        assert reg.active_tool == TOOL_ROTATE
        assert manip.tool == TOOL_ROTATE

    def test_r_selects_scale(self):
        reg, manip, _ = self._make()
        assert reg.handle_key_event(ord("R"), 0, True) is True
        assert reg.active_tool == TOOL_SCALE
        assert manip.tool == TOOL_SCALE

    def test_w_e_r_cycle(self):
        reg, manip, _ = self._make()
        reg.handle_key_event(ord("E"), 0, True)  # rotate
        reg.handle_key_event(ord("R"), 0, True)  # scale
        reg.handle_key_event(ord("W"), 0, True)  # translate
        assert manip.assignments[-3:] == [TOOL_ROTATE, TOOL_SCALE, TOOL_TRANSLATE]

    def test_ctrl_w_ignored(self):
        reg, manip, _ = self._make()
        # modifiers bit 1 = Ctrl (see manipulator_registry._MOD_CTRL).
        changed = reg.handle_key_event(ord("W"), 1 << 1, True)
        assert changed is False
        assert reg.active_tool == TOOL_TRANSLATE

    def test_shift_e_ignored(self):
        reg, manip, _ = self._make()
        changed = reg.handle_key_event(ord("E"), 1 << 0, True)
        assert changed is False
        assert reg.active_tool == TOOL_TRANSLATE

    def test_alt_r_ignored(self):
        reg, manip, _ = self._make()
        changed = reg.handle_key_event(ord("R"), 1 << 2, True)
        assert changed is False
        assert reg.active_tool == TOOL_TRANSLATE

    def test_key_up_is_ignored(self):
        reg, manip, _ = self._make()
        changed = reg.handle_key_event(ord("E"), 0, False)
        assert changed is False
        assert reg.active_tool == TOOL_TRANSLATE

    def test_unknown_key_ignored(self):
        reg, manip, _ = self._make()
        changed = reg.handle_key_event(ord("Q"), 0, True)
        assert changed is False
        assert reg.active_tool == TOOL_TRANSLATE

    def test_same_tool_press_is_noop(self):
        reg, manip, _ = self._make()
        baseline = list(manip.assignments)
        # Start in translate; pressing W should not trigger another push.
        reg.handle_key_event(ord("W"), 0, True)
        assert manip.assignments == baseline


# -- settings write-through and subscription -------------------------------


class TestSettingsIntegration:
    def test_hotkey_writes_through_to_settings(self):
        s = Settings()
        manip = _StubManipulator()
        reg = ToolRegistry(settings=s, manipulator=manip)
        reg.handle_key_event(ord("R"), 0, True)
        assert s.get(ACTIVE_TOOL_SETTING) == TOOL_SCALE

    def test_settings_change_propagates_to_manipulator(self):
        s = Settings()
        manip = _StubManipulator()
        reg = ToolRegistry(settings=s, manipulator=manip)
        s.set(ACTIVE_TOOL_SETTING, TOOL_ROTATE)
        assert reg.active_tool == TOOL_ROTATE
        assert manip.tool == TOOL_ROTATE

    def test_invalid_settings_change_ignored(self):
        s = Settings()
        manip = _StubManipulator()
        reg = ToolRegistry(settings=s, manipulator=manip)
        s.set(ACTIVE_TOOL_SETTING, "bogus")
        assert reg.active_tool == TOOL_TRANSLATE

    def test_destroy_unsubscribes(self):
        s = Settings()
        manip = _StubManipulator()
        reg = ToolRegistry(settings=s, manipulator=manip)
        reg.destroy()
        # After destroy, setting mutations no longer propagate.
        s.set(ACTIVE_TOOL_SETTING, TOOL_SCALE)
        assert reg.active_tool == TOOL_TRANSLATE

    def test_destroy_is_idempotent(self):
        reg = ToolRegistry(settings=Settings())
        reg.destroy()
        reg.destroy()  # no exception

    def test_on_tool_changed_callback_fires(self):
        events = []
        reg = ToolRegistry(
            settings=Settings(),
            manipulator=_StubManipulator(),
            on_tool_changed=lambda old, new: events.append((old, new)),
        )
        reg.handle_key_event(ord("E"), 0, True)
        reg.handle_key_event(ord("R"), 0, True)
        assert events == [(TOOL_TRANSLATE, TOOL_ROTATE), (TOOL_ROTATE, TOOL_SCALE)]


# -- attach_manipulator --------------------------------------------------


class TestAttachManipulator:
    def test_attach_after_construction_pushes_current_tool(self):
        s = Settings()
        s.set(ACTIVE_TOOL_SETTING, TOOL_SCALE)
        reg = ToolRegistry(settings=s)
        manip = _StubManipulator()
        reg.attach_manipulator(manip)
        assert manip.tool == TOOL_SCALE

    def test_manipulator_failure_does_not_crash(self):
        class Boom:
            @property
            def tool(self) -> str:
                return TOOL_TRANSLATE

            @tool.setter
            def tool(self, v: str) -> None:
                raise RuntimeError("not ready")

        reg = ToolRegistry(settings=Settings(), manipulator=Boom())
        # This path exercised set_active_tool → _apply_to_manipulator.
        reg.set_active_tool(TOOL_ROTATE)
        assert reg.active_tool == TOOL_ROTATE  # registry still updated


# -- direct set_active_tool -----------------------------------------------


class TestSetActiveTool:
    def test_set_active_tool_rejects_invalid(self):
        reg = ToolRegistry()
        with pytest.raises(ValueError):
            reg.set_active_tool("nope")

    def test_set_active_tool_idempotent(self):
        manip = _StubManipulator()
        reg = ToolRegistry(manipulator=manip)
        baseline = list(manip.assignments)
        reg.set_active_tool(TOOL_TRANSLATE)  # same as current
        assert manip.assignments == baseline
