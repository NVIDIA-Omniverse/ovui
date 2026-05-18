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

Settings is a dict-backed store with subscriber
notifications on change and JSON persistence.
"""

import json
import os
import weakref
from typing import Any, Callable, Optional

_SENTINEL = object()

_DEFAULTS: dict = {
    "ui.theme": "dark",
    "app.recent_files": [],
    "layout.save_path": "~/.ovgear/layout.json",
    "viewport.camera.fov": 45.0,
    "viewport.camera.near": 0.1,
    "viewport.camera.far": 10000.0,
    "viewport.manipulator.active_tool": "translate",
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


class Subscription:
    """RAII subscription handle. Call cancel() to unsubscribe."""

    def __init__(
        self,
        settings_ref: "weakref.ref[Any]",
        key: str,
        callback: Callable,
    ) -> None:
        self._settings_ref = settings_ref
        self._key = key
        self._callback = callback
        self._cancelled = False

    def cancel(self) -> None:
        """Remove this subscriber from the settings store."""
        if self._cancelled:
            return
        self._cancelled = True
        settings = self._settings_ref()
        if settings is not None:
            settings._remove_subscriber(self._key, self._callback)

    def __del__(self) -> None:
        self.cancel()


class Settings:
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

        Called by :class:`ovwidgets.app.application.Application` at
        ``__init__`` (with the live store) and at ``shutdown`` (with
        ``None`` to clear). Tests that need isolation can also call this
        with a freshly-constructed ``Settings`` and reset to ``None`` at
        teardown.
        """
        cls._instance = settings

    def __init__(self) -> None:
        self._data: dict = {}
        self._subscribers: dict[str, list[Callable]] = {}
        for key, value in _DEFAULTS.items():
            # Deep-copy mutable defaults so instances don't share state.
            if isinstance(value, list):
                self._data[key] = list(value)
            elif isinstance(value, dict):
                self._data[key] = dict(value)
            else:
                self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value. Returns default if key doesn't exist."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a setting value. Notifies subscribers only if value changed."""
        old = self._data.get(key, _SENTINEL)
        if old is not _SENTINEL and old == value:
            return
        self._data[key] = value
        for cb in list(self._subscribers.get(key, [])):
            cb(key, value)

    def get_string(self, key: str, default: str = "") -> str:
        """Convenience: get a setting value as a string."""
        val = self.get(key, default)
        return str(val)

    def subscribe(self, key: str, callback: Callable[[str, Any], None]) -> Subscription:
        """Subscribe to changes on a key. Returns a cancellable Subscription."""
        if key not in self._subscribers:
            self._subscribers[key] = []
        self._subscribers[key].append(callback)
        return Subscription(weakref.ref(self), key, callback)

    def _remove_subscriber(self, key: str, callback: Callable) -> None:
        subs = self._subscribers.get(key)
        if subs and callback in subs:
            subs.remove(callback)

    def load_from_file(self, path: str) -> None:
        """Load settings from a JSON file, merging with existing settings.

        Notifies subscribers for any keys whose values changed.
        Raises FileNotFoundError if the file doesn't exist.
        """
        with open(path) as f:
            data = json.load(f)
        for key, value in data.items():
            self.set(key, value)

    def save_to_file(self, path: str) -> None:
        """Save current settings to a JSON file, creating parent dirs as needed."""
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self._data, f, indent=2)
