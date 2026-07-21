# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""LayerSettings — persistent Layer-window configuration (LAYERS-PLAN Step 52).

Wraps :class:`ovui_widgets.common.settings.Settings` with typed boolean properties for
every toggle Kit exposes in the Layers window's Options button dropdown
(LAYERS-WINDOW-ARCHITECTURE §15). Reads and writes are routed through the
owning :class:`Settings` instance so values persist across app restarts
via the existing JSON save/load pipeline.

The attribute surface mirrors :class:`DefaultLayerSettings` — the
stand-in used by headless tests before Step 52 — so :class:`LayerModel`
and every other call site can consume either interchangeably. Writes
through the setter persist immediately (same tick) and notify every
subscriber registered via :meth:`subscribe`.

Step 53 wires the Options-button checkbox dropdown into these setters;
:class:`LayerModel` already subscribes to change notifications so a
toggle flips the tree shape without a manual rebuild call.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from ovui_widgets.common.settings import Settings, Subscription

# Map from property name to ``(persistent settings key, default value)``.
# Keys live under the ``layers.`` namespace so :meth:`Settings.save_to_file`
# round-trips them alongside the rest of the app-level config. Defaults
# match LAYERS-WINDOW-ARCHITECTURE §15 (Kit's factory defaults).
LAYER_SETTINGS_KEYS: Dict[str, Tuple[str, bool]] = {
    "show_session_layer": ("layers.show_session_layer", True),
    "show_layer_contents": ("layers.show_layer_contents", True),
    "show_missing_reference": ("layers.show_missing_reference", True),
    "show_info_notification": ("layers.show_info_notification", True),
    "show_merge_or_flatten_warning": (
        "layers.show_merge_or_flatten_warning",
        True,
    ),
    "show_layer_file_extension": (
        "layers.show_layer_file_extension",
        True,
    ),
    "show_metricsassembler_layer": (
        "layers.show_metricsassembler_layer",
        False,
    ),
    "file_dialog_show_root_layer_location": (
        "layers.file_dialog_show_root_layer_location",
        False,
    ),
    "enable_auto_authoring_mode": (
        "layers.enable_auto_authoring_mode",
        False,
    ),
    "enable_spec_linking_mode": (
        "layers.enable_spec_linking_mode",
        False,
    ),
}

# Subset of keys whose change reshapes :meth:`LayerModel.get_item_children`
# output. :class:`LayerModel` subscribes to these to fire a full
# ``_item_changed(None)`` rebuild when one flips. The rest (toast /
# dialog / suffix toggles) are read on-demand by their call sites so
# no repaint is needed.
TREE_REBUILD_KEYS: frozenset = frozenset(
    {
        "layers.show_session_layer",
        "layers.show_layer_contents",
        "layers.show_metricsassembler_layer",
        "layers.show_layer_file_extension",
    }
)


class LayerSettings:
    """Persistent Layer-window configuration backed by :class:`Settings`.

    Attribute surface matches :class:`DefaultLayerSettings` so
    :class:`LayerModel` can consume either class with no type branching
    at the read site. Writes through each setter hit the backing
    :class:`Settings` instance, which serialises the value to the JSON
    config on next save and notifies every subscriber synchronously.
    """

    def __init__(self, app_settings: Settings) -> None:
        """Bind to ``app_settings`` (usually ``Application.settings``).

        The bound store is the single source of truth — the wrapper
        itself carries no state beyond a reference to it, which means
        multiple :class:`LayerSettings` instances over the same
        :class:`Settings` round-trip values to each other for free.
        """
        self._s = app_settings

    @property
    def settings(self) -> Settings:
        """Return the backing :class:`Settings` store."""
        return self._s

    # ── Tree-shape toggles (LAYERS-WINDOW-ARCHITECTURE §15) ────────────

    @property
    def show_session_layer(self) -> bool:
        return bool(self._s.get("layers.show_session_layer", True))

    @show_session_layer.setter
    def show_session_layer(self, value: bool) -> None:
        self._s.set("layers.show_session_layer", bool(value))

    @property
    def show_layer_contents(self) -> bool:
        return bool(self._s.get("layers.show_layer_contents", True))

    @show_layer_contents.setter
    def show_layer_contents(self, value: bool) -> None:
        self._s.set("layers.show_layer_contents", bool(value))

    @property
    def show_metricsassembler_layer(self) -> bool:
        return bool(
            self._s.get("layers.show_metricsassembler_layer", False)
        )

    @show_metricsassembler_layer.setter
    def show_metricsassembler_layer(self, value: bool) -> None:
        self._s.set("layers.show_metricsassembler_layer", bool(value))

    @property
    def show_layer_file_extension(self) -> bool:
        return bool(self._s.get("layers.show_layer_file_extension", True))

    @show_layer_file_extension.setter
    def show_layer_file_extension(self, value: bool) -> None:
        self._s.set("layers.show_layer_file_extension", bool(value))

    # ── Notification / dialog toggles ─────────────────────────────────

    @property
    def show_missing_reference(self) -> bool:
        return bool(self._s.get("layers.show_missing_reference", True))

    @show_missing_reference.setter
    def show_missing_reference(self, value: bool) -> None:
        self._s.set("layers.show_missing_reference", bool(value))

    @property
    def show_info_notification(self) -> bool:
        return bool(self._s.get("layers.show_info_notification", True))

    @show_info_notification.setter
    def show_info_notification(self, value: bool) -> None:
        self._s.set("layers.show_info_notification", bool(value))

    @property
    def show_merge_or_flatten_warning(self) -> bool:
        return bool(
            self._s.get("layers.show_merge_or_flatten_warning", True)
        )

    @show_merge_or_flatten_warning.setter
    def show_merge_or_flatten_warning(self, value: bool) -> None:
        self._s.set("layers.show_merge_or_flatten_warning", bool(value))

    # ── File-dialog / live-mode toggles ───────────────────────────────

    @property
    def file_dialog_show_root_layer_location(self) -> bool:
        return bool(
            self._s.get(
                "layers.file_dialog_show_root_layer_location", False
            )
        )

    @file_dialog_show_root_layer_location.setter
    def file_dialog_show_root_layer_location(self, value: bool) -> None:
        self._s.set(
            "layers.file_dialog_show_root_layer_location", bool(value)
        )

    @property
    def enable_auto_authoring_mode(self) -> bool:
        return bool(self._s.get("layers.enable_auto_authoring_mode", False))

    @enable_auto_authoring_mode.setter
    def enable_auto_authoring_mode(self, value: bool) -> None:
        self._s.set("layers.enable_auto_authoring_mode", bool(value))

    @property
    def enable_spec_linking_mode(self) -> bool:
        return bool(self._s.get("layers.enable_spec_linking_mode", False))

    @enable_spec_linking_mode.setter
    def enable_spec_linking_mode(self, value: bool) -> None:
        self._s.set("layers.enable_spec_linking_mode", bool(value))

    # ── Subscription helpers ──────────────────────────────────────────

    def subscribe(
        self, callback: Callable[[str, Any], None]
    ) -> List[Subscription]:
        """Subscribe ``callback`` to every Layer setting key.

        Returns one :class:`Subscription` per key so the caller can
        cancel the lot in a single loop on teardown. ``callback``
        receives the usual ``(key, new_value)`` pair — callers that
        only care about a subset of keys filter inside the callback.
        """
        return [
            self._s.subscribe(key, callback)
            for _, (key, _default) in LAYER_SETTINGS_KEYS.items()
        ]

    def subscribe_tree_rebuild(
        self, callback: Callable[[str, Any], None]
    ) -> List[Subscription]:
        """Subscribe ``callback`` only to tree-shape keys (Step 52).

        :class:`LayerModel` uses this narrower hook so a flip of a
        toast-or-dialog toggle (e.g. ``show_info_notification``) does
        not trigger a full :meth:`_item_changed` walk. The caller
        still owns cancellation — one :class:`Subscription` is
        returned per key so teardown stays ``for sub in subs:
        sub.cancel()``.
        """
        return [
            self._s.subscribe(key, callback)
            for key in TREE_REBUILD_KEYS
        ]
