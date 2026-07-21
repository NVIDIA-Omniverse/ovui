# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Persistent application settings.

Generic storage/observer behavior lives in
``ovui_data_adapters.services.settings``. This module preserves the historical
``ovui_widgets.common.settings`` path while keeping ovui-widgets-specific defaults
and process singleton wiring on the widget/app side.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional

from ovui_data_adapters.services.settings import Settings as _SettingsBase
from ovui_data_adapters.services.settings import Subscription

_MISSING = object()

# Kit-compatible main run-loop FPS cap. Canonical path from Kit's
# omni.kit.loop-default (RunLoopRunner.cpp: "/app/runLoops" +
# "/main/rateLimitFrequency"); Kit ships 120 in its extension.toml.
RATE_LIMIT_FPS_SETTING_KEY = "app.runLoops.main.rateLimitFrequency"
DEFAULT_RATE_LIMIT_FPS = 120.0


def valid_rate_limit_fps(value: Any, default: Optional[float]) -> Optional[float]:
    """Return a positive finite FPS cap, or ``default`` for bad values.

    Booleans are rejected rather than coerced (True would silently become a
    1 FPS cap). ``default=None`` lets callers distinguish "invalid" from a
    usable value.
    """

    if isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result) or result <= 0.0:
        return default
    return result


def _rate_limit_fps_is_valid(value: Any) -> bool:
    return valid_rate_limit_fps(value, default=None) is not None


# Per-key write validators enforced at the store boundary (runtime ``set``,
# CLI launch overrides, and persisted-file loads, which route through
# ``set``). Rejecting invalid values before they enter the store keeps
# visible, effective, and persisted state coherent by construction: a bad
# runtime write cannot shadow a launch-local CLI overlay or replace a valid
# persisted baseline.
_KEY_VALIDATORS: dict = {
    RATE_LIMIT_FPS_SETTING_KEY: _rate_limit_fps_is_valid,
}

_DEFAULTS: dict = {
    "ui.theme": "dark",
    "app.recent_files": [],
    # Kit-compatible main run-loop FPS cap (omni.kit.loop-default's
    # /app/runLoops/main/rateLimitFrequency; Kit ships 120).
    "app.runLoops.main.rateLimitFrequency": 120.0,
    "layout.save_path": "~/.ovgear/layout.json",
    "viewport.camera.fov": 45.0,
    "viewport.camera.near": 0.1,
    "viewport.camera.far": 10000.0,
    "viewport.manipulator.active_tool": "translate",
    "snap.enabled": False,
    "snap.grid_size": 1.0,
    # Layers window (LAYERS-PLAN Step 52 / LAYERS-WINDOW-ARCHITECTURE §15).
    # Mirror LayerSettings' documented defaults so a fresh settings file
    # persists the factory state on first save_to_file.
    "layers.show_session_layer": True,
    "layers.show_layer_contents": True,
    "layers.show_missing_reference": True,
    "layers.show_info_notification": True,
    "layers.show_merge_or_flatten_warning": True,
    "layers.show_layer_file_extension": True,
    "layers.show_metricsassembler_layer": False,
    "layers.file_dialog_show_root_layer_location": False,
    "layers.enable_auto_authoring_mode": False,
    "layers.enable_spec_linking_mode": False,
}


class Settings(_SettingsBase):
    """
    Key-value settings store with pub/sub notification and JSON persistence.

    This is OvGear's replacement for Kit's carb.settings. Simple dict-backed
    store with subscriber notifications on value changes.

    Process-wide singleton accessor (added in implementation Step 2 per
    Rev 8 §5.1 + Plan Rev 2 §4 Step 2): :meth:`Settings.instance` returns
    the singleton; :meth:`Settings.set_instance` registers / clears it.
    Application registers its own ``Settings`` instance at startup so widget
    code can read the same store via ``Settings.instance()`` without
    reaching into ``Application.instance().settings``. Until Application
    registers, ``instance()`` returns a freshly-constructed default
    instance — useful in unit tests that exercise widget code without a
    live application.
    """

    _instance: "Optional[Settings]" = None

    @classmethod
    def instance(cls) -> "Settings":
        """Return the process-wide ``Settings`` instance (lazy default)."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def set_instance(cls, settings: "Optional[Settings]") -> None:
        """Register / clear the process-wide ``Settings`` instance.

        Called by :class:`ovui_widgets.app.application.Application` at
        ``__init__`` (with the live store) and at ``shutdown`` (with
        ``None`` to clear). Tests that need isolation can also call this
        with a freshly-constructed ``Settings`` and reset to ``None`` at
        teardown.
        """
        cls._instance = settings

    def __init__(self) -> None:
        super().__init__(_DEFAULTS)
        # Launch-local override values (``--/path/to/key=value`` on the app
        # command line). They win over defaults and persisted values for
        # reads in this process, but live outside ``_data`` so
        # ``save_to_file`` never persists them. A runtime ``set`` on an
        # overridden key commits that key to the store (and thus to
        # persistence) — an explicit change is a real preference again.
        self._launch_overrides: dict[str, Any] = {}

    @staticmethod
    def _rejects(key: str, value: Any) -> bool:
        """True when a per-key validator rejects ``value`` for ``key``."""
        validator = _KEY_VALIDATORS.get(key)
        if validator is None or validator(value):
            return False
        from ovui_widgets.common.error_reporter import ErrorReporter
        ErrorReporter.log_warning(
            "Settings",
            f"rejecting invalid value {value!r} for {key!r}; "
            "keeping the current value",
        )
        return True

    def apply_launch_overrides(self, overrides: Mapping[str, Any]) -> None:
        """Install launch-local override values.

        Each key reads back with the override value until it is explicitly
        ``set`` at runtime. Subscribers are notified when the visible value
        changes, matching :meth:`set` semantics. Values a per-key validator
        rejects are skipped (with a warning), leaving the persisted /
        default value in effect.
        """
        for key, value in overrides.items():
            if self._rejects(key, value):
                continue
            old_visible = self.get(key, _MISSING)
            self._launch_overrides[key] = value
            if old_visible is _MISSING or old_visible != value:
                for cb in list(self._subscribers.get(key, [])):
                    cb(key, value)

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._launch_overrides:
            return self._launch_overrides[key]
        return super().get(key, default)

    def set(self, key: str, value: Any) -> None:
        # Per-key validation happens before any state changes hands, so an
        # invalid write cannot pop a launch-local overlay or replace a valid
        # persisted value — visible/effective/persisted state stay coherent.
        if self._rejects(key, value):
            return
        override = self._launch_overrides.pop(key, _MISSING)
        if override is _MISSING:
            super().set(key, value)
            return
        # Commit to the persistent store unconditionally (the user made an
        # explicit choice, even if it equals the override), but notify only
        # when the visible value actually changes.
        self._data[key] = value
        if override != value:
            for cb in list(self._subscribers.get(key, [])):
                cb(key, value)


__all__ = [
    "DEFAULT_RATE_LIMIT_FPS",
    "RATE_LIMIT_FPS_SETTING_KEY",
    "Settings",
    "Subscription",
    "valid_rate_limit_fps",
]
