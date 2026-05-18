# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 6.1 — abstract ``PropertyWidget`` base + ``PropertyWindow`` rename.

Covers:

* :mod:`ovwidgets.property.widget` — the new subpackage that re-exports the
  abstract :class:`PropertyWidget` base.
* :class:`ovwidgets.property.widget.PropertyWidget` — the ABC cannot be
  instantiated directly, sync and async build hooks match ``PropertyWidget``,
  and the default ``request_rebuild`` / ``destroy`` /
  ``build_items_async`` no-op so minimal subclasses compile.
* :class:`ovwidgets.property.window.PropertyWindow` — the renamed class is
  still a :class:`ovwidgets.common.managed_window.ManagedWindow`, still
  instantiable, still exposes the ``set_adapter`` / ``set_selection``
  API Phase 5 leaves in place, and owns a :attr:`_widgets` list that
  :meth:`_rebuild_content` iterates.
* Compat alias — ``from ovwidgets.property import PropertyWidget`` still
  resolves to :class:`PropertyWindow` so
  :meth:`ovwidgets.app.application.Application.create_windows` doesn't break.
* Widget iteration — registered widgets get :meth:`on_new_payload` and
  :meth:`build_items` called in registration order. The payload is an
  :class:`ovwidgets.property.payload.PropertyPayload` built from the current
  selection.
"""

from typing import List

import pytest

# ---------------------------------------------------------------------------
# Helpers — concrete subclasses and headless PropertyWindow factory
# ---------------------------------------------------------------------------


class _RecordingWidget:
    """Concrete :class:`PropertyWidget` that logs its lifecycle.

    Not a real subclass at import time — built inside the tests via
    :meth:`_make_widget_class` so each test gets a fresh subclass.
    Keeps the module-level namespace free of ABC-registered subclasses
    that could leak into other tests.
    """


def _make_widget_class(on_new_payload_return: bool = True):
    """Build a concrete :class:`PropertyWidget` subclass per-test.

    ``on_new_payload_return`` controls whether the widget reports it
    wants to show for the current payload — the Step 6.1 wiring must
    honour both branches so the test parameterises both.
    """
    from ovwidgets.property.widget import PropertyWidget

    class _Concrete(PropertyWidget):
        def __init__(self) -> None:
            self.on_new_payload_calls: list = []
            self.build_items_calls: int = 0
            self.destroy_calls: int = 0

        def on_new_payload(self, payload) -> bool:  # type: ignore[override]
            self.on_new_payload_calls.append(payload)
            return on_new_payload_return

        def build_items(self) -> None:  # type: ignore[override]
            self.build_items_calls += 1

        def destroy(self) -> None:  # type: ignore[override]
            self.destroy_calls += 1

    return _Concrete


def _make_headless_window():
    """:class:`PropertyWindow` with no live ui.Window — bypasses ``__init__``.

    Mirrors the pattern used across the existing property tests (see
    ``_make_headless`` in ``test_property_widget.py``). We set only the
    fields ``_rebuild_content`` touches so the tests can exercise the
    widget-iteration path without an initialised ovui root.
    """
    from ovwidgets.property.window import PropertyWindow
    w = PropertyWindow.__new__(PropertyWindow)
    w._adapter = None
    w._selection = []
    w._filter_text = ""
    w._pending_filter_handle = None
    w._filter_field = None
    w._content = None
    w._group_collapse_state = {}
    w._active_context_menu = None
    w._bus_sub = None
    w._stage_adapter = None
    w._stage_change_sub = None
    w._undo_manager_ref = None
    w._widgets: List = []
    w._window = None
    # Step 6.5: ``PropertyWindow.__init__`` always sets this field; the
    # bypass-__init__ helper must mirror that so ``destroy`` does not
    # ``AttributeError`` on the new tear-down path.
    w._default_attributes = None
    # Step 7.3: bypass-__init__ tests exercise ``_rebuild_content``
    # directly; set the two scroll-related fields to their no-op
    # sentinels (``_scroll_frame=None`` makes ``ScrollPreserver``
    # save/restore a no-op, ``_scroll_preserver=None`` makes the
    # rebuild skip the preserver calls entirely). Either shape keeps
    # the rebuild path compatible with headless tests.
    w._scroll_frame = None
    w._scroll_preserver = None
    return w


# ---------------------------------------------------------------------------
# Package / import shape
# ---------------------------------------------------------------------------


class TestPackageStructure:
    def test_widget_subpackage_importable(self):
        import ovwidgets.property
        import ovwidgets.property.widget  # noqa: F401

    def test_property_widget_abstract_module_importable(self):
        import ovwidgets.property.widget.property_widget as mod
        assert mod.PropertyWidget is not None

    def test_widget_subpackage_reexports_base(self):
        from ovwidgets.property.widget import PropertyWidget as Base
        from ovwidgets.property.widget.property_widget import PropertyWidget as Direct
        assert Base is Direct

    def test_window_module_importable(self):
        from ovwidgets.property.window import PropertyWindow
        assert PropertyWindow is not None

    def test_top_level_exports(self):
        import ovwidgets.property
        assert hasattr(ovwidgets.property, "PropertyPayload")
        assert hasattr(ovwidgets.property, "PropertyWindow")
        assert hasattr(ovwidgets.property, "PropertyWidget")


# ---------------------------------------------------------------------------
# Compat alias — ``from ovwidgets.property import PropertyWidget`` → PropertyWindow
# ---------------------------------------------------------------------------


class TestCompatAlias:
    def test_top_level_propertywidget_is_propertywindow(self):
        """Step 6.1: the top-level ``PropertyWidget`` name is a
        DEPRECATED alias for :class:`PropertyWindow` so
        :meth:`ovwidgets.app.application.Application.create_windows` keeps
        working unchanged."""
        from ovwidgets.property import PropertyWidget as Alias
        from ovwidgets.property.window import PropertyWindow
        assert Alias is PropertyWindow

    def test_compat_alias_is_managed_window(self):
        from ovwidgets.common.managed_window import ManagedWindow
        from ovwidgets.property import PropertyWidget as Alias
        assert issubclass(Alias, ManagedWindow)

    def test_compat_alias_is_not_abstract_base(self):
        """The top-level alias must NOT be the new abstract base — the
        two classes share a name but sit in different namespaces."""
        from ovwidgets.property import PropertyWidget as Alias
        from ovwidgets.property.widget import PropertyWidget as Base
        assert Alias is not Base

    def test_abstract_base_is_not_managed_window(self):
        """The abstract widget is a pure ABC — it has no
        :class:`ManagedWindow` lineage."""
        from ovwidgets.common.managed_window import ManagedWindow
        from ovwidgets.property.widget import PropertyWidget as Base
        assert not issubclass(Base, ManagedWindow)


# ---------------------------------------------------------------------------
# Abstract ``PropertyWidget`` base — cannot be instantiated, has the public API
# ---------------------------------------------------------------------------


class TestAbstractPropertyWidget:
    def test_cannot_instantiate_directly(self):
        """ABC guard — the bare base refuses ``__init__`` because
        ``on_new_payload`` and ``build_items`` are still abstract."""
        from ovwidgets.property.widget import PropertyWidget
        with pytest.raises(TypeError):
            PropertyWidget()  # type: ignore[abstract]

    def test_subclass_missing_build_items_cannot_instantiate(self):
        from ovwidgets.property.widget import PropertyWidget

        class _Partial(PropertyWidget):  # type: ignore[abstract]
            def on_new_payload(self, payload) -> bool:  # type: ignore[override]
                return False

        with pytest.raises(TypeError):
            _Partial()  # type: ignore[abstract]

    def test_subclass_missing_on_new_payload_cannot_instantiate(self):
        from ovwidgets.property.widget import PropertyWidget

        class _Partial(PropertyWidget):  # type: ignore[abstract]
            def build_items(self) -> None:  # type: ignore[override]
                pass

        with pytest.raises(TypeError):
            _Partial()  # type: ignore[abstract]

    def test_concrete_subclass_instantiates_cleanly(self):
        cls = _make_widget_class()
        w = cls()
        assert w is not None

    def test_has_on_new_payload(self):
        from ovwidgets.property.widget import PropertyWidget
        assert hasattr(PropertyWidget, "on_new_payload")

    def test_has_build_items(self):
        from ovwidgets.property.widget import PropertyWidget
        assert hasattr(PropertyWidget, "build_items")

    def test_has_build_items_async(self):
        from ovwidgets.property.widget import PropertyWidget
        assert hasattr(PropertyWidget, "build_items_async")

    def test_has_request_rebuild(self):
        from ovwidgets.property.widget import PropertyWidget
        assert hasattr(PropertyWidget, "request_rebuild")

    def test_has_destroy(self):
        from ovwidgets.property.widget import PropertyWidget
        assert hasattr(PropertyWidget, "destroy")

    def test_build_items_async_default_is_none(self):
        """Minimal subclasses should not need to override the async
        path — the base returns ``None`` so the host falls back to
        sync :meth:`build_items`."""
        cls = _make_widget_class()
        assert cls().build_items_async() is None

    def test_request_rebuild_default_is_no_op(self):
        cls = _make_widget_class()
        cls().request_rebuild()  # must not raise

    def test_destroy_default_is_no_op(self):
        """The abstract base's ``destroy`` no-ops. Our recording
        subclass overrides it; this test uses the unoverridden default
        via a fresh subclass that only implements the abstract pair."""
        from ovwidgets.property.widget import PropertyWidget

        class _NoOverride(PropertyWidget):
            def on_new_payload(self, payload) -> bool:  # type: ignore[override]
                return False

            def build_items(self) -> None:  # type: ignore[override]
                pass

        _NoOverride().destroy()  # must not raise


# ---------------------------------------------------------------------------
# ``PropertyWindow`` — renamed class + widget list scaffolding
# ---------------------------------------------------------------------------


class TestPropertyWindowShape:
    def test_is_managed_window_subclass(self):
        from ovwidgets.common.managed_window import ManagedWindow
        from ovwidgets.property.window import PropertyWindow
        assert issubclass(PropertyWindow, ManagedWindow)

    def test_widgets_field_starts_empty(self):
        w = _make_headless_window()
        assert w._widgets == []

    def test_register_widget_appends(self):
        w = _make_headless_window()
        cls = _make_widget_class()
        child = cls()
        w.register_widget(child)
        assert w._widgets == [child]

    def test_register_widget_preserves_order(self):
        w = _make_headless_window()
        cls = _make_widget_class()
        a, b, c = cls(), cls(), cls()
        w.register_widget(a)
        w.register_widget(b)
        w.register_widget(c)
        assert w._widgets == [a, b, c]

    def test_unregister_widget_removes(self):
        w = _make_headless_window()
        cls = _make_widget_class()
        child = cls()
        w.register_widget(child)
        w.unregister_widget(child)
        assert w._widgets == []

    def test_unregister_widget_calls_destroy(self):
        w = _make_headless_window()
        cls = _make_widget_class()
        child = cls()
        w.register_widget(child)
        w.unregister_widget(child)
        assert child.destroy_calls == 1

    def test_unregister_unknown_widget_is_no_op(self):
        """Removing a widget that was never registered must not raise —
        mirrors Kit's ``PropertyWindow.unregister_widget`` semantics."""
        w = _make_headless_window()
        cls = _make_widget_class()
        stranger = cls()
        w.unregister_widget(stranger)  # must not raise
        assert stranger.destroy_calls == 0


# ---------------------------------------------------------------------------
# ``_build_registered_widgets`` iteration semantics
# ---------------------------------------------------------------------------


class TestPropertyWindowWidgetIteration:
    def test_no_widgets_no_crash(self):
        w = _make_headless_window()
        w._build_registered_widgets()  # empty list → no-op

    def test_iterates_on_new_payload_in_registration_order(self):
        w = _make_headless_window()
        w._selection = ["/World/A"]
        cls = _make_widget_class()
        a, b, c = cls(), cls(), cls()
        w._widgets = [a, b, c]
        w._build_registered_widgets()
        for widget in (a, b, c):
            assert len(widget.on_new_payload_calls) == 1

    def test_build_items_called_only_when_on_new_payload_true(self):
        w = _make_headless_window()
        w._selection = ["/World/A"]
        accepter = _make_widget_class(on_new_payload_return=True)()
        rejecter = _make_widget_class(on_new_payload_return=False)()
        w._widgets = [accepter, rejecter]
        w._build_registered_widgets()
        assert accepter.build_items_calls == 1
        assert rejecter.build_items_calls == 0

    def test_on_new_payload_receives_property_payload(self):
        """Step 6.1 wraps the current selection in a
        :class:`PropertyPayload` before dispatching so widgets can
        inspect ``payload.get_scheme()`` (property metadata behavior)."""
        from ovwidgets.property.payload import PropertyPayload

        w = _make_headless_window()
        w._selection = ["/World/A", "/World/B"]
        cls = _make_widget_class()
        child = cls()
        w._widgets = [child]
        w._build_registered_widgets()
        [payload] = child.on_new_payload_calls
        assert isinstance(payload, PropertyPayload)
        assert payload.paths == ["/World/A", "/World/B"]

    def test_destroy_destroys_all_widgets(self):
        w = _make_headless_window()
        cls = _make_widget_class()
        a, b = cls(), cls()
        w._widgets = [a, b]
        # PropertyWindow.destroy() calls super().destroy() which touches
        # self._window — keep that as None via __new__ bypass.
        from ovwidgets.property.window import PropertyWindow
        PropertyWindow.destroy(w)
        assert a.destroy_calls == 1
        assert b.destroy_calls == 1
        assert w._widgets == []
