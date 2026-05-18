# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the attribute-row context menu — Step 7.2.

the property inspector 7.2 done-signal matrix:

* Right-click on an attribute row's outer ``ui.HStack`` routes through
  :func:`ovwidgets.property.attribute_row._wire_row_context_menu` with
  ``button == 1`` → the driver pops :class:`ui.Menu` at ``(x, y)``.
* ``copy_value`` stores ``{type_name, value}`` in the module-level
  clipboard under the requested ``clipboard_id``.
* ``paste_value`` reads the clipboard and writes via
  ``adapter.set_value`` wrapped in ``begin_edit`` / ``end_edit`` only
  when the stored ``type_name`` matches the target attr's type and the
  target is neither locked nor clipboard-``None``.
* ``reset_value`` calls ``adapter.clear_value`` on the target attr;
  locked / unimplemented / ABC-default cases short-circuit.
* ``copy_attribute_path`` composes ``"/<path>.<attr>"`` and stores it
  in the path clipboard namespace.
* ``can_paste`` / ``can_reset`` disable the menu items in the obvious
  dead-end cases (empty clipboard, type mismatch, locked, adapter's
  ``clear_value`` is the ABC default, unauthored attr).

The tests exercise the pure helpers against a
:class:`~ovwidgets.common.testing.mock_property.MockPropertyAdapter` (no USD,
no ``omni.ui`` import), plus headless behavioural tests for the
row-level right-click routing. The ``show_attr_context_menu`` driver
itself is not tested end-to-end because building a real ``ui.Menu``
requires an initialised ``omni.ui`` root — the disabled/enabled
predicate wiring (the observable piece) is covered by the pure-helper
tests.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter

from ovwidgets.common.testing.mock_property import MockPropertyAdapter
from ovwidgets.property.parts.attr_context_menu import (
    DEFAULT_CLIPBOARD_ID,
    PATH_CLIPBOARD_ID,
    can_paste,
    can_reset,
    clear_clipboard,
    compose_attribute_path,
    copy_attribute_path,
    copy_value,
    get_clipboard,
    paste_value,
    reset_value,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _meta(
    name: str,
    type_name: str = "float",
    is_locked: bool = False,
    is_authored: bool = True,
) -> AttributeMetadata:
    """Minimal AttributeMetadata for clipboard/paste tests.

    Default ``is_authored=True`` so :func:`can_reset` doesn't short-
    circuit on unrelated branches; override when a test pins the
    unauthored behaviour.
    """
    return AttributeMetadata(
        name=name,
        display_name=name,
        type_name=type_name,
        value_type=float,
        group="",
        is_locked=is_locked,
        is_authored=is_authored,
    )


def _adapter_with(
    values: Dict[str, Any],
    metas: Optional[Dict[str, AttributeMetadata]] = None,
    paths: Optional[List[str]] = None,
) -> MockPropertyAdapter:
    """Instantiate a :class:`MockPropertyAdapter` seeded with ``values``."""
    if metas is None:
        metas = {name: _meta(name) for name in values}
    adapter = MockPropertyAdapter(
        paths=paths if paths is not None else ["/World/X"],
        attributes=metas,
    )
    for name, value in values.items():
        adapter.set_value(name, value)
    return adapter


class _RecordingAdapter(MockPropertyAdapter):
    """Adapter subclass that records each ``clear_value`` + edit call.

    Needed because ``can_reset`` checks the *class*-level override of
    :meth:`PropertyAdapter.clear_value`, not the instance. Subclassing
    lets tests pin both the pure-helper behaviour (which calls
    ``clear_value`` directly) and the gate predicate (which inspects
    the type) with one adapter.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.cleared: List[str] = []
        self.edit_sequence: List[str] = []

    def clear_value(self, attr_name: str) -> None:
        self.cleared.append(attr_name)
        self._values.pop(attr_name, None)

    def begin_edit(self, attr_name: str) -> None:  # type: ignore[override]
        super().begin_edit(attr_name)
        self.edit_sequence.append(f"begin:{attr_name}")

    def end_edit(self, attr_name: str) -> None:  # type: ignore[override]
        super().end_edit(attr_name)
        self.edit_sequence.append(f"end:{attr_name}")

    def set_value(self, attr_name: str, value: Any) -> None:  # type: ignore[override]
        super().set_value(attr_name, value)
        self.edit_sequence.append(f"set:{attr_name}={value}")


class _UnimplementedClearAdapter(MockPropertyAdapter):
    """Adapter whose ``clear_value`` raises on one specific attr.

    Exercises the inline ``NotImplementedError`` catch in
    :func:`reset_value`: the class-level override makes
    :func:`can_reset` return ``True``, but the runtime path on the
    "bad" attr raises — :func:`reset_value` must swallow the raise
    and return ``False`` rather than propagating.
    """

    def __init__(self, *args: Any, bad_attr: str = "", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._bad_attr = bad_attr

    def clear_value(self, attr_name: str) -> None:
        if attr_name == self._bad_attr:
            raise NotImplementedError("bad attr")
        self._values.pop(attr_name, None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_clipboard():
    """Drop every clipboard namespace before and after each test.

    The attribute clipboard is module-level and survives across tests
    by design — so Copy in test A could pollute Paste in test B.
    Autouse fixture forces a clean slate so ordering doesn't matter.
    Also clears the path clipboard namespace.
    """
    clear_clipboard()
    yield
    clear_clipboard()


# ---------------------------------------------------------------------------
# compose_attribute_path — path string composition
# ---------------------------------------------------------------------------


class TestComposeAttributePath:
    """``compose_attribute_path`` is the primitive Copy Attribute Path uses."""

    def test_single_path(self) -> None:
        adapter = _adapter_with({"radius": 1.0}, paths=["/World/Cube"])
        assert compose_attribute_path(adapter, "radius") == "/World/Cube.radius"

    def test_multi_selection_picks_first(self) -> None:
        """Multi-selection collapses to the first path — the clipboard
        holds a single string, not a list. Mirrors Kit's "Copy
        Attribute Path" on a multi-selection.
        """
        adapter = _adapter_with(
            {"height": 2.0},
            paths=["/World/A", "/World/B", "/World/C"],
        )
        assert compose_attribute_path(adapter, "height") == "/World/A.height"

    def test_empty_path_list_returns_dot_attr(self) -> None:
        """No paths → ".attr_name" — the ``.`` separator is preserved
        so the caller can detect the degenerate case by string.startswith.
        """
        adapter = MockPropertyAdapter(
            paths=[], attributes={"name": _meta("name")},
        )
        assert compose_attribute_path(adapter, "name") == ".name"

    def test_nested_prim_path(self) -> None:
        adapter = _adapter_with(
            {"intensity": 5.0},
            paths=["/World/Lights/KeyLight"],
        )
        assert (
            compose_attribute_path(adapter, "intensity")
            == "/World/Lights/KeyLight.intensity"
        )


# ---------------------------------------------------------------------------
# copy_value — snapshots value + type_name into clipboard
# ---------------------------------------------------------------------------


class TestCopyValue:

    def test_copy_stores_value_and_type(self) -> None:
        adapter = _adapter_with({"radius": 1.5})
        record = copy_value(adapter, "radius")
        assert record == {"type_name": "float", "value": 1.5}
        assert get_clipboard() == {"type_name": "float", "value": 1.5}

    def test_copy_preserves_metadata_type_name(self) -> None:
        """The stored ``type_name`` is the METADATA type_name, not the
        Python type of the value. Paste gates on this string match.
        """
        metas = {"color": _meta("color", type_name="color3f")}
        adapter = _adapter_with({"color": (0.5, 0.5, 0.5)}, metas=metas)
        record = copy_value(adapter, "color")
        assert record["type_name"] == "color3f"

    def test_copy_ambiguous_stores_none(self) -> None:
        """Multi-selection with differing values → value is None; the
        clipboard records the None so a later Paste can detect + skip.
        """
        metas = {"radius": _meta("radius")}
        adapter = MockPropertyAdapter(
            paths=["/A", "/B"], attributes=metas,
        )
        adapter.set_path_value("/A", "radius", 1.0)
        adapter.set_path_value("/B", "radius", 2.0)
        record = copy_value(adapter, "radius")
        assert record["value"] is None
        assert record["type_name"] == "float"

    def test_copy_overwrites_stale_snapshot(self) -> None:
        """A second Copy in the same namespace replaces the prior snapshot."""
        adapter = _adapter_with({"a": 1.0, "b": 2.0})
        copy_value(adapter, "a")
        copy_value(adapter, "b")
        assert get_clipboard() == {"type_name": "float", "value": 2.0}

    def test_copy_custom_clipboard_id(self) -> None:
        """Different ``clipboard_id`` → separate namespace, no collision."""
        adapter = _adapter_with({"a": 1.0, "b": 2.0})
        copy_value(adapter, "a", clipboard_id="ns1")
        copy_value(adapter, "b", clipboard_id="ns2")
        assert get_clipboard("ns1") == {"type_name": "float", "value": 1.0}
        assert get_clipboard("ns2") == {"type_name": "float", "value": 2.0}


# ---------------------------------------------------------------------------
# paste_value — applies clipboard value when type-compatible
# ---------------------------------------------------------------------------


class TestPasteValue:

    def test_paste_writes_value(self) -> None:
        """Normal flow: Copy A, Paste B (same type) → B gets A's value."""
        metas = {"a": _meta("a"), "b": _meta("b")}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        adapter.set_value("a", 42.0)
        adapter.set_value("b", 0.0)
        copy_value(adapter, "a")
        written = paste_value(adapter, "b")
        assert written is True
        assert adapter.get_value("b") == 42.0

    def test_paste_wraps_begin_end_edit(self) -> None:
        """Paste routes through ``begin_edit`` / ``end_edit`` so undo and
        change subscribers fire (same code path as an inline edit).
        """
        metas = {"a": _meta("a"), "b": _meta("b")}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        adapter.set_value("a", 42.0)
        adapter.edit_sequence.clear()
        copy_value(adapter, "a")
        paste_value(adapter, "b")
        assert adapter.edit_sequence == [
            "begin:b",
            "set:b=42.0",
            "end:b",
        ]

    def test_paste_disabled_for_type_mismatch(self) -> None:
        """Clipboard ``type_name="float"`` must NOT paste into a ``string`` target."""
        metas = {
            "num": _meta("num", type_name="float"),
            "name": _meta("name", type_name="string"),
        }
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        adapter.set_value("num", 42.0)
        adapter.set_value("name", "original")
        copy_value(adapter, "num")
        written = paste_value(adapter, "name")
        assert written is False
        assert adapter.get_value("name") == "original"
        # No edit envelope was opened.
        assert "begin:name" not in adapter.edit_sequence

    def test_paste_disabled_when_target_locked(self) -> None:
        """Locked target silently rejects Paste — mirrors the group-menu convention."""
        metas = {
            "a": _meta("a"),
            "b": _meta("b", is_locked=True),
        }
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        adapter.set_value("a", 42.0)
        adapter.set_value("b", 99.0)
        copy_value(adapter, "a")
        written = paste_value(adapter, "b")
        assert written is False
        assert adapter.get_value("b") == 99.0

    def test_paste_disabled_for_empty_clipboard(self) -> None:
        metas = {"a": _meta("a")}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        adapter.set_value("a", 42.0)
        written = paste_value(adapter, "a")
        assert written is False

    def test_paste_disabled_when_clipboard_value_is_none(self) -> None:
        """Ambiguous Copy → None in clipboard → Paste refuses (don't
        clobber a concrete value with "mixed").
        """
        metas = {"a": _meta("a")}
        adapter_src = MockPropertyAdapter(
            paths=["/A", "/B"], attributes=metas,
        )
        adapter_src.set_path_value("/A", "a", 1.0)
        adapter_src.set_path_value("/B", "a", 2.0)
        copy_value(adapter_src, "a")

        adapter_dst = _RecordingAdapter(
            paths=["/World/Y"], attributes=metas,
        )
        adapter_dst.set_value("a", 5.0)
        written = paste_value(adapter_dst, "a")
        assert written is False
        assert adapter_dst.get_value("a") == 5.0


# ---------------------------------------------------------------------------
# reset_value — calls clear_value on the target attr
# ---------------------------------------------------------------------------


class TestResetValue:

    def test_reset_calls_clear_value(self) -> None:
        metas = {"radius": _meta("radius")}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        adapter.set_value("radius", 1.0)
        result = reset_value(adapter, "radius")
        assert result is True
        assert adapter.cleared == ["radius"]

    def test_reset_disabled_when_target_locked(self) -> None:
        metas = {"radius": _meta("radius", is_locked=True)}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        result = reset_value(adapter, "radius")
        assert result is False
        assert adapter.cleared == []

    def test_reset_returns_false_when_adapter_raises_not_implemented(self) -> None:
        """Adapter-side NotImplementedError is swallowed and surfaces as
        a "False" return, not a raise. Mirrors the group-menu inline
        catch.
        """
        metas = {"a": _meta("a"), "b": _meta("b")}
        adapter = _UnimplementedClearAdapter(
            paths=["/World/X"],
            attributes=metas,
            bad_attr="b",
        )
        assert reset_value(adapter, "a") is True
        assert reset_value(adapter, "b") is False

    def test_reset_on_abc_default_raises(self) -> None:
        """Adapters whose ``clear_value`` IS the ABC default propagate
        the NotImplementedError → surfaces as False. The call-site
        must treat this identically to a class-level unimplemented
        adapter so tests covering both branches cross-check.
        """
        class _NoResetAdapter(PropertyAdapter):
            """Adapter with no ``clear_value`` override."""

            def get_paths(self) -> List[str]:
                return ["/World/X"]

            def is_valid(self) -> bool:
                return True

            def get_attribute_names(self) -> List[str]:
                return ["a"]

            def get_attribute_metadata(self, attr_name: str) -> AttributeMetadata:
                return _meta(attr_name)

            def get_value(self, attr_name: str) -> Any:
                return 1.0

            def is_ambiguous(self, attr_name: str) -> bool:
                return False

            def get_per_component_ambiguity(self, attr_name: str) -> Optional[List[bool]]:
                return None

            def begin_edit(self, attr_name: str) -> None:
                pass

            def set_value(self, attr_name: str, value: Any) -> None:
                pass

            def end_edit(self, attr_name: str) -> None:
                pass

            def subscribe_changes(self, callback: Any) -> Any:
                return None

            def get_scheme(self) -> str:
                return "noreset"

        adapter = _NoResetAdapter()
        # ABC default raises; the helper catches the raise and returns False.
        assert reset_value(adapter, "a") is False


# ---------------------------------------------------------------------------
# copy_attribute_path — writes path string to path clipboard namespace
# ---------------------------------------------------------------------------


class TestCopyAttributePath:

    def test_copy_path_stores_full_string(self) -> None:
        adapter = _adapter_with(
            {"radius": 1.0},
            paths=["/World/Cube"],
        )
        path = copy_attribute_path(adapter, "radius")
        assert path == "/World/Cube.radius"
        assert get_clipboard(PATH_CLIPBOARD_ID) == "/World/Cube.radius"

    def test_copy_path_does_not_touch_value_clipboard(self) -> None:
        """Path clipboard namespace is DISTINCT from the value clipboard;
        Copy Path does NOT clobber a prior Copy Value.
        """
        adapter = _adapter_with({"radius": 1.5})
        copy_value(adapter, "radius")
        copy_attribute_path(adapter, "radius")
        # Value clipboard survives the path copy.
        assert get_clipboard() == {"type_name": "float", "value": 1.5}
        # Path clipboard now holds the path string.
        assert get_clipboard(PATH_CLIPBOARD_ID) == "/World/X.radius"

    def test_copy_path_overwrites_stale(self) -> None:
        adapter = _adapter_with(
            {"a": 1.0, "b": 2.0},
            paths=["/P"],
        )
        copy_attribute_path(adapter, "a")
        copy_attribute_path(adapter, "b")
        assert get_clipboard(PATH_CLIPBOARD_ID) == "/P.b"


# ---------------------------------------------------------------------------
# can_paste — menu-item enable predicate for Paste Value
# ---------------------------------------------------------------------------


class TestCanPaste:

    def test_empty_clipboard(self) -> None:
        adapter = _adapter_with({"a": 1.0})
        assert can_paste(adapter, "a") is False

    def test_type_match_and_unlocked(self) -> None:
        adapter = _adapter_with({"a": 1.0, "b": 2.0})
        copy_value(adapter, "a")
        assert can_paste(adapter, "b") is True

    def test_type_mismatch(self) -> None:
        metas = {
            "num": _meta("num", type_name="float"),
            "name": _meta("name", type_name="string"),
        }
        adapter = _adapter_with({"num": 1.0, "name": "hello"}, metas=metas)
        copy_value(adapter, "num")
        assert can_paste(adapter, "name") is False

    def test_locked_target(self) -> None:
        metas = {
            "a": _meta("a"),
            "b": _meta("b", is_locked=True),
        }
        adapter = _adapter_with({"a": 1.0, "b": 2.0}, metas=metas)
        copy_value(adapter, "a")
        assert can_paste(adapter, "b") is False

    def test_clipboard_value_none(self) -> None:
        metas = {"a": _meta("a")}
        adapter = MockPropertyAdapter(
            paths=["/A", "/B"], attributes=metas,
        )
        adapter.set_path_value("/A", "a", 1.0)
        adapter.set_path_value("/B", "a", 2.0)
        copy_value(adapter, "a")
        # Same adapter targets itself; value is still None.
        assert can_paste(adapter, "a") is False

    def test_custom_clipboard_id(self) -> None:
        """``can_paste`` checks the requested ``clipboard_id`` namespace."""
        adapter = _adapter_with({"a": 1.0})
        copy_value(adapter, "a", clipboard_id="ns1")
        assert can_paste(adapter, "a", clipboard_id="ns1") is True
        assert can_paste(adapter, "a", clipboard_id="ns2") is False


# ---------------------------------------------------------------------------
# can_reset — menu-item enable predicate for Reset to Default
# ---------------------------------------------------------------------------


class TestCanReset:

    def test_adapter_with_clear_value_and_authored(self) -> None:
        metas = {"a": _meta("a", is_authored=True)}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        assert can_reset(adapter, "a") is True

    def test_abc_default_adapter_disabled(self) -> None:
        """``MockPropertyAdapter`` alone inherits the ABC default —
        ``can_reset`` returns False.
        """
        metas = {"a": _meta("a")}
        adapter = MockPropertyAdapter(
            paths=["/World/X"], attributes=metas,
        )
        assert can_reset(adapter, "a") is False

    def test_locked_attr_disabled(self) -> None:
        metas = {"a": _meta("a", is_locked=True)}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        assert can_reset(adapter, "a") is False

    def test_unauthored_attr_disabled(self) -> None:
        """Already at default → nothing to clear → disabled."""
        metas = {"a": _meta("a", is_authored=False)}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        assert can_reset(adapter, "a") is False


# ---------------------------------------------------------------------------
# Clipboard utilities — namespace isolation, defensive copy
# ---------------------------------------------------------------------------


class TestClipboardUtilities:

    def test_clear_single_namespace_preserves_other(self) -> None:
        adapter = _adapter_with({"a": 1.0})
        copy_value(adapter, "a")
        copy_attribute_path(adapter, "a")
        clear_clipboard(DEFAULT_CLIPBOARD_ID)
        assert get_clipboard(DEFAULT_CLIPBOARD_ID) is None
        assert get_clipboard(PATH_CLIPBOARD_ID) == "/World/X.a"

    def test_clear_all(self) -> None:
        adapter = _adapter_with({"a": 1.0})
        copy_value(adapter, "a")
        copy_attribute_path(adapter, "a")
        clear_clipboard()
        assert get_clipboard(DEFAULT_CLIPBOARD_ID) is None
        assert get_clipboard(PATH_CLIPBOARD_ID) is None

    def test_get_clipboard_returns_defensive_copy(self) -> None:
        adapter = _adapter_with({"a": 1.0})
        copy_value(adapter, "a")
        snapshot = get_clipboard()
        assert isinstance(snapshot, dict)
        snapshot["value"] = 999.0
        # Module-level state unchanged.
        assert get_clipboard()["value"] == 1.0

    def test_get_clipboard_unknown_id_returns_none(self) -> None:
        assert get_clipboard("never_populated") is None


# ---------------------------------------------------------------------------
# Row-level right-click wiring — headless HStack stand-in
# ---------------------------------------------------------------------------


class _FakeHStackWithMouseRelease:
    """Stand-in for ``ui.HStack`` that captures mouse-release wiring."""

    def __init__(self) -> None:
        self.mouse_released_fn = None

    def set_mouse_released_fn(self, fn: Any) -> None:
        self.mouse_released_fn = fn


class _FakeRowOwner:
    """Minimal stand-in for an attribute row instance.

    :func:`_wire_row_context_menu` only reads ``_prop`` and ``_adapter``
    and writes ``_active_context_menu``; everything else on a real row
    (widgets, model, subscribers) is irrelevant to the wiring check.
    """

    def __init__(self, prop: AttributeMetadata, adapter: PropertyAdapter) -> None:
        self._prop = prop
        self._adapter = adapter
        self._active_context_menu: Optional[Any] = None


class TestRowContextMenuWiring:
    """``_wire_row_context_menu`` routes button==1 clicks to the driver."""

    def test_right_click_fires_context_menu_callback(self, monkeypatch) -> None:
        """button == 1 (right-click) pops the menu and pins the return value."""
        from ovwidgets.property.attribute_row import _wire_row_context_menu
        from ovwidgets.property.parts import attr_context_menu as ctx_mod

        calls: List[Any] = []
        sentinel_menu = object()

        def _spy_show(adapter, prop, x, y, clipboard_id=DEFAULT_CLIPBOARD_ID,
                      path_clipboard_id=PATH_CLIPBOARD_ID):
            calls.append((prop.name, x, y))
            return sentinel_menu

        monkeypatch.setattr(ctx_mod, "show_attr_context_menu", _spy_show)

        prop = _meta("radius")
        adapter = _adapter_with({"radius": 1.0}, metas={"radius": prop})
        owner = _FakeRowOwner(prop, adapter)
        hstack = _FakeHStackWithMouseRelease()

        _wire_row_context_menu(hstack, owner)
        hstack.mouse_released_fn(10.0, 20.0, 1, 0)

        assert calls == [("radius", 10.0, 20.0)]
        assert owner._active_context_menu is sentinel_menu

    def test_left_click_ignored(self, monkeypatch) -> None:
        from ovwidgets.property.attribute_row import _wire_row_context_menu
        from ovwidgets.property.parts import attr_context_menu as ctx_mod

        calls: List[Any] = []
        monkeypatch.setattr(
            ctx_mod, "show_attr_context_menu",
            lambda *a, **k: (calls.append(a), object())[1],
        )
        prop = _meta("radius")
        adapter = _adapter_with({"radius": 1.0}, metas={"radius": prop})
        owner = _FakeRowOwner(prop, adapter)
        hstack = _FakeHStackWithMouseRelease()

        _wire_row_context_menu(hstack, owner)
        hstack.mouse_released_fn(10.0, 20.0, 0, 0)

        assert calls == []
        assert owner._active_context_menu is None

    def test_middle_click_ignored(self, monkeypatch) -> None:
        from ovwidgets.property.attribute_row import _wire_row_context_menu
        from ovwidgets.property.parts import attr_context_menu as ctx_mod

        calls: List[Any] = []
        monkeypatch.setattr(
            ctx_mod, "show_attr_context_menu",
            lambda *a, **k: (calls.append(a), object())[1],
        )
        prop = _meta("radius")
        adapter = _adapter_with({"radius": 1.0}, metas={"radius": prop})
        owner = _FakeRowOwner(prop, adapter)
        hstack = _FakeHStackWithMouseRelease()

        _wire_row_context_menu(hstack, owner)
        hstack.mouse_released_fn(10.0, 20.0, 2, 0)

        assert calls == []

    def test_wiring_registered_on_hstack(self) -> None:
        """``_wire_row_context_menu`` must install a handler — otherwise
        the right-click would never reach the driver.
        """
        from ovwidgets.property.attribute_row import _wire_row_context_menu

        prop = _meta("radius")
        adapter = _adapter_with({"radius": 1.0}, metas={"radius": prop})
        owner = _FakeRowOwner(prop, adapter)
        hstack = _FakeHStackWithMouseRelease()

        _wire_row_context_menu(hstack, owner)
        assert hstack.mouse_released_fn is not None

    def test_consecutive_right_clicks_replace_active_menu(self, monkeypatch) -> None:
        """Each right-click overwrites the pinned menu; the previous
        reference is dropped so omni.ui's refcount closes the stale
        popup.
        """
        from ovwidgets.property.attribute_row import _wire_row_context_menu
        from ovwidgets.property.parts import attr_context_menu as ctx_mod

        menus = [object(), object()]
        calls = [0]

        def _spy_show(adapter, prop, x, y, clipboard_id=DEFAULT_CLIPBOARD_ID,
                      path_clipboard_id=PATH_CLIPBOARD_ID):
            i = calls[0]
            calls[0] += 1
            return menus[i]

        monkeypatch.setattr(ctx_mod, "show_attr_context_menu", _spy_show)

        prop = _meta("radius")
        adapter = _adapter_with({"radius": 1.0}, metas={"radius": prop})
        owner = _FakeRowOwner(prop, adapter)
        hstack = _FakeHStackWithMouseRelease()

        _wire_row_context_menu(hstack, owner)
        hstack.mouse_released_fn(0.0, 0.0, 1, 0)
        assert owner._active_context_menu is menus[0]
        hstack.mouse_released_fn(5.0, 5.0, 1, 0)
        assert owner._active_context_menu is menus[1]


# ---------------------------------------------------------------------------
# End-to-end: copy → paste across re-selection
# ---------------------------------------------------------------------------


class TestEndToEndAttrClipboard:
    """Compose the helpers into the realistic user flow.

    These tests don't touch the UI — they drive the helpers directly
    in the order the menu callbacks would, then assert the adapter
    state. Catches any wiring regression in the helper quartet.
    """

    def test_copy_paste_roundtrip(self) -> None:
        metas = {"radius": _meta("radius")}
        adapter = _RecordingAdapter(
            paths=["/World/Cube"], attributes=metas,
        )
        adapter.set_value("radius", 1.0)

        copy_value(adapter, "radius")
        # User drifts the value editing inline.
        adapter.set_value("radius", 99.0)
        # Paste restores the snapshot.
        assert paste_value(adapter, "radius") is True
        assert adapter.get_value("radius") == 1.0

    def test_reset_after_copy_preserves_clipboard(self) -> None:
        """Reset must not touch the clipboard (confirms namespacing)."""
        metas = {"a": _meta("a")}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        adapter.set_value("a", 5.0)
        copy_value(adapter, "a")
        assert get_clipboard() == {"type_name": "float", "value": 5.0}

        reset_value(adapter, "a")
        # Clipboard survives the reset; paste would still restore the value.
        assert get_clipboard() == {"type_name": "float", "value": 5.0}

    def test_switch_selection_preserves_clipboard(self) -> None:
        """Copy on Selection A, paste on Selection B's same-named attr."""
        metas = {"radius": _meta("radius")}
        adapter_a = _adapter_with({"radius": 7.0}, metas=metas)
        copy_value(adapter_a, "radius")

        adapter_b = _RecordingAdapter(
            paths=["/World/Y"], attributes=metas,
        )
        adapter_b.set_value("radius", 0.0)
        assert paste_value(adapter_b, "radius") is True
        assert adapter_b.get_value("radius") == 7.0

    def test_copy_path_and_copy_value_coexist(self) -> None:
        """Both clipboard namespaces can be populated simultaneously;
        a subsequent action in either namespace only touches its own.
        """
        metas = {"radius": _meta("radius")}
        adapter = _adapter_with(
            {"radius": 1.5},
            metas=metas,
            paths=["/World/Cube"],
        )
        copy_value(adapter, "radius")
        copy_attribute_path(adapter, "radius")
        assert get_clipboard() == {"type_name": "float", "value": 1.5}
        assert get_clipboard(PATH_CLIPBOARD_ID) == "/World/Cube.radius"
        # A new Copy Value stays in its own namespace.
        adapter.set_value("radius", 2.5)
        copy_value(adapter, "radius")
        assert get_clipboard() == {"type_name": "float", "value": 2.5}
        assert get_clipboard(PATH_CLIPBOARD_ID) == "/World/Cube.radius"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
