# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Mock PropertyAdapter for development and testing (no USD required).

MockPropertyAdapter implements every abstract method of PropertyAdapter using
an in-memory attribute dict.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter


def _is_vector_value(v: Any) -> bool:
    """True if ``v`` is a vector-like container (has ``len``, not a string/bytes)."""
    return v is not None and hasattr(v, "__len__") and not isinstance(v, (str, bytes))


class _MockPropertySubscription:
    def __init__(self, owner: "MockPropertyAdapter", callback: Callable) -> None:
        self._owner = owner
        self._callback = callback

    def cancel(self) -> None:
        try:
            self._owner._subscribers.remove(self._callback)
        except ValueError:
            pass

    def __del__(self) -> None:
        self.cancel()


class MockPropertyAdapter(PropertyAdapter):
    """In-memory PropertyAdapter backed by a dict of AttributeMetadata.

    Supports per-path value storage for multi-selection ambiguity testing.
    Call set_path_value(path, attr, value) to simulate prims with different
    values; is_ambiguous() will then return True for that attribute.
    """

    def __init__(
        self,
        paths: Optional[List[str]] = None,
        attributes: Optional[Dict[str, AttributeMetadata]] = None,
        scheme: str = "mock",
    ) -> None:
        self._paths: List[str] = list(paths) if paths else []
        self._attributes: Dict[str, AttributeMetadata] = dict(attributes) if attributes else {}
        self._values: Dict[str, Any] = {}
        self._per_path_values: Dict[str, Dict[str, Any]] = {}
        self._subscribers: List[Callable] = []
        self._edits: List[Tuple[str, str]] = []
        # Step 3.6: per-attribute resolved asset paths. Populated via
        # :meth:`set_resolved_asset_path`; read via
        # :meth:`get_resolved_asset_path` to exercise the tooltip path in
        # ``AssetPathAttributeRow``. Defaults to ``None`` (inherits the
        # ABC's ``None`` default) when the attribute isn't registered.
        self._resolved_asset_paths: Dict[str, str] = {}
        # Step 6.4: configurable scheme so tests can drive
        # :class:`SchemaPropertyWidget`'s ``on_new_payload`` gate without
        # subclassing. Defaults to ``"mock"`` to preserve prior behaviour.
        self._scheme: str = scheme

    # ── PropertyAdapter ABC ───────────────────────────────────────────────────

    def get_paths(self) -> List[str]:
        return list(self._paths)

    def is_valid(self) -> bool:
        return True

    def get_attribute_names(self) -> List[str]:
        return list(self._attributes.keys())

    def get_attribute_metadata(self, attr_name: str) -> AttributeMetadata:
        return self._attributes[attr_name]

    def get_value(self, attr_name: str) -> Any:
        """Return None when attribute values differ across selected paths (mixed)."""
        if self.is_ambiguous(attr_name):
            return None
        if self._paths:
            path_vals = self._per_path_values.get(self._paths[0], {})
            if attr_name in path_vals:
                return path_vals[attr_name]
        return self._values.get(attr_name)

    def is_ambiguous(self, attr_name: str) -> bool:
        """Return True if the attribute has different values across selected paths."""
        if len(self._paths) <= 1:
            return False
        per_path = [
            self._per_path_values.get(p, {}).get(attr_name, self._values.get(attr_name))
            for p in self._paths
        ]
        return len(set(str(v) for v in per_path)) > 1

    def get_per_component_ambiguity(self, attr_name: str) -> Optional[List[bool]]:
        """Per-channel ambiguity for vector attributes; ``None`` for scalars.

        For a vector attribute whose values are tuples/lists (e.g. ``(x, y, z)``),
        returns a list of booleans — one per component — where ``True`` marks
        channels that differ across the selected paths. For a scalar attribute
        (or an unknown/absent attribute), returns ``None``. See property metadata behavior.
        """
        values = self._collect_path_values(attr_name)
        if not values:
            return None
        first = values[0]
        if not _is_vector_value(first):
            return None
        return [
            any(v is None or v[i] != first[i] for v in values[1:])
            for i in range(len(first))
        ]

    def _collect_path_values(self, attr_name: str) -> List[Any]:
        if self._paths:
            return [
                self._per_path_values.get(p, {}).get(attr_name, self._values.get(attr_name))
                for p in self._paths
            ]
        v = self._values.get(attr_name)
        return [v] if v is not None else []

    def begin_edit(self, attr_name: str) -> None:
        self._edits.append(("begin", attr_name))

    def set_value(self, attr_name: str, value: Any) -> None:
        """Write value to all selected paths (simulates multi-selection set)."""
        self._values[attr_name] = value
        for path in self._paths:
            if path not in self._per_path_values:
                self._per_path_values[path] = {}
            self._per_path_values[path][attr_name] = value

    def end_edit(self, attr_name: str) -> None:
        self._edits.append(("end", attr_name))

    def subscribe_changes(self, callback: Callable[[], None]) -> "_MockPropertySubscription":  # type: ignore[override]
        self._subscribers.append(callback)
        return _MockPropertySubscription(self, callback)

    def get_scheme(self) -> str:
        return self._scheme

    def set_scheme(self, scheme: str) -> None:
        """Override the scheme reported by :meth:`get_scheme`.

        Step 6.4 test helper so a single mock instance can drive both
        the "schema matches" and "schema differs" branches of
        :meth:`SchemaPropertyWidget.on_new_payload` without
        re-constructing the adapter. The constructor's ``scheme``
        kwarg covers the common "fixed at construction" case; this
        setter covers mid-test mutation.
        """
        self._scheme = scheme

    def get_resolved_asset_path(self, attr_name: str) -> Optional[str]:
        """Return the resolved asset path registered for ``attr_name``.

        Returns ``None`` when no resolved path was seeded via
        :meth:`set_resolved_asset_path` — matches the :class:`PropertyAdapter`
        ABC default so callers can rely on "``None`` means no tooltip"
        without branching on adapter scheme.
        """
        return self._resolved_asset_paths.get(attr_name)

    # ── Test helpers ──────────────────────────────────────────────────────────

    def set_path_value(self, path: str, attr_name: str, value: Any) -> None:
        """Set a per-path value for ambiguity simulation in tests."""
        if path not in self._per_path_values:
            self._per_path_values[path] = {}
        self._per_path_values[path][attr_name] = value

    def set_resolved_asset_path(self, attr_name: str, resolved: Optional[str]) -> None:
        """Seed the resolved asset path surfaced by
        :meth:`get_resolved_asset_path`. Passing ``None`` clears a prior
        seed so tests can cover both the "tooltip present" and "tooltip
        absent" branches of :class:`AssetPathAttributeRow`.
        """
        if resolved is None:
            self._resolved_asset_paths.pop(attr_name, None)
        else:
            self._resolved_asset_paths[attr_name] = str(resolved)

    def fire_change(self) -> None:
        """Invoke all subscribers (simulates an attribute change)."""
        for cb in list(self._subscribers):
            cb()
