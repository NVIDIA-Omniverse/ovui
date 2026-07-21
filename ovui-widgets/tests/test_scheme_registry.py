# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 6.5 — :class:`PropertySchemeRegistry`.

Covers the Step 6.5 done-signal checklist from the property inspector implementation:

* :class:`PropertySchemeRegistry` is importable from the widget
  subpackage.
* :meth:`instance` returns the same singleton on every call; the
  singleton survives across calls but can be reset for test
  isolation via :meth:`_reset_for_tests`.
* :meth:`register_widget` stores a zero-arg factory under
  ``(scheme, name)``; returns a :class:`_WidgetSubscription` whose
  :meth:`cancel` unregisters.
* :meth:`register_scheme_delegate` stores a delegate under
  ``(scheme, name)``; returns a :class:`_DelegateSubscription` whose
  :meth:`cancel` unregisters.
* :meth:`get_widgets_for_payload` returns ordered widget instances
  merging ``"default"`` entries with the requested scheme's entries.
* Registration order is preserved within same ``order``.
* ``top_stack=True`` wins the tiebreak among entries with the same
  ``order``.
* ``"default"`` scheme is universal — a widget registered under
  ``"default"`` surfaces for every payload scheme, so
  :class:`AttributesWidget` keeps appearing after Step 6.6 starts
  branching on ``payload.get_scheme()``.
* Module-import registration: the default singleton has
  :class:`AttributesWidget` registered for scheme ``"default"``.
* Duplicate ``(scheme, name)`` raises :class:`ValueError`.
* Subscription :meth:`cancel` is idempotent.

Every test that touches the singleton resets it at setup / teardown
so one test's registrations never leak into another's assertions.
"""

from __future__ import annotations

from typing import Any, List

import pytest

from ovui_widgets.property.payload import PropertyPayload
from ovui_widgets.property.widget import (
    AttributesWidget,
    PropertySchemeRegistry,
    PropertyWidget,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _RecordingWidget(PropertyWidget):
    """Minimal :class:`PropertyWidget` that records when it was built.

    The registry invokes ``factory()`` to produce an instance; tests
    assert identity / order via the ``tag`` stashed at construction.
    """

    def __init__(self, tag: str = "w") -> None:
        self.tag = tag
        self.build_calls = 0

    def on_new_payload(self, payload: PropertyPayload) -> bool:
        return True

    def build_items(self) -> None:
        self.build_calls += 1


def _factory(tag: str):
    """Return a zero-arg factory producing a new :class:`_RecordingWidget`.

    Each invocation yields a fresh instance so the test can assert
    that the registry calls the factory on every
    :meth:`get_widgets_for_payload`.
    """
    def _build() -> _RecordingWidget:
        return _RecordingWidget(tag=tag)
    return _build


@pytest.fixture(autouse=True)
def _reset_registry_between_tests():
    """Reset the singleton before and after every test.

    Rebuilding the singleton re-runs :func:`_register_defaults` so
    each test observes the baseline ``"default"`` → AttributesWidget
    mapping regardless of registration churn elsewhere in the suite.
    """
    PropertySchemeRegistry._reset_for_tests()
    yield
    PropertySchemeRegistry._reset_for_tests()


# ---------------------------------------------------------------------------
# Import shape
# ---------------------------------------------------------------------------


class TestImportShape:
    def test_importable_from_widget_subpackage(self):
        from ovui_widgets.property.widget import PropertySchemeRegistry as R
        assert R is not None

    def test_importable_from_direct_module(self):
        from ovui_widgets.property.widget.scheme_registry import PropertySchemeRegistry as R
        assert R is not None

    def test_re_export_identity(self):
        from ovui_widgets.property.widget import PropertySchemeRegistry as A
        from ovui_widgets.property.widget.scheme_registry import PropertySchemeRegistry as B
        assert A is B

    def test_in_widget_subpackage_all(self):
        import ovui_widgets.property.widget as w_mod
        assert "PropertySchemeRegistry" in w_mod.__all__


# ---------------------------------------------------------------------------
# Singleton semantics
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_instance_returns_same_object(self):
        a = PropertySchemeRegistry.instance()
        b = PropertySchemeRegistry.instance()
        assert a is b

    def test_reset_drops_singleton(self):
        a = PropertySchemeRegistry.instance()
        PropertySchemeRegistry._reset_for_tests()
        b = PropertySchemeRegistry.instance()
        assert a is not b

    def test_reset_restores_default_attributes_registration(self):
        """A fresh singleton must re-register :class:`AttributesWidget`
        under ``"default"``; otherwise Step 6.2's catch-all behaviour
        would drop the first time a test reset the registry."""
        PropertySchemeRegistry._reset_for_tests()
        widgets = PropertySchemeRegistry.instance().get_widgets_for_payload(
            "default", PropertyPayload(paths=[])
        )
        assert any(isinstance(w, AttributesWidget) for w in widgets)


# ---------------------------------------------------------------------------
# Default registration — AttributesWidget for "default" scheme
# ---------------------------------------------------------------------------


class TestDefaultRegistration:
    def test_default_scheme_includes_attributes_widget(self):
        """The done-signal check from the property inspector step 6.5."""
        widgets = PropertySchemeRegistry.instance().get_widgets_for_payload(
            "default", PropertyPayload(paths=[])
        )
        assert any(isinstance(w, AttributesWidget) for w in widgets)

    def test_default_attributes_widget_surfaces_for_non_default_scheme(self):
        """The ``"default"`` scheme is universal — widgets registered
        there appear for every payload scheme, not just
        ``payload.scheme == "default"``."""
        widgets = PropertySchemeRegistry.instance().get_widgets_for_payload(
            "light", PropertyPayload(paths=[], scheme="light")
        )
        assert any(isinstance(w, AttributesWidget) for w in widgets)

    def test_default_registration_uses_attributes_widget_class_as_factory(self):
        """The module-import registration uses the class itself as a
        zero-arg factory; invoking it must produce a windowless
        :class:`AttributesWidget` (``window=None`` default)."""
        widgets = PropertySchemeRegistry.instance().get_widgets_for_payload(
            "default", PropertyPayload(paths=[])
        )
        attrs = [w for w in widgets if isinstance(w, AttributesWidget)]
        assert len(attrs) == 1
        assert attrs[0]._window is None


# ---------------------------------------------------------------------------
# register_widget
# ---------------------------------------------------------------------------


class TestRegisterWidget:
    def test_registers_and_returns_subscription(self):
        reg = PropertySchemeRegistry.instance()
        sub = reg.register_widget("light", "light", _factory("light"))
        assert hasattr(sub, "cancel")

    def test_registered_widget_surfaces_in_matching_scheme(self):
        reg = PropertySchemeRegistry.instance()
        reg.register_widget("light", "light", _factory("light"))
        widgets = reg.get_widgets_for_payload(
            "light", PropertyPayload(paths=[], scheme="light")
        )
        tags = [getattr(w, "tag", None) for w in widgets]
        assert "light" in tags

    def test_registered_widget_absent_for_other_schemes(self):
        reg = PropertySchemeRegistry.instance()
        reg.register_widget("light", "light", _factory("light"))
        widgets = reg.get_widgets_for_payload(
            "camera", PropertyPayload(paths=[], scheme="camera")
        )
        tags = [getattr(w, "tag", None) for w in widgets]
        assert "light" not in tags

    def test_two_widgets_for_same_scheme_both_appear(self):
        """The task's done-signal #1: register a second widget for a
        scheme, both appear."""
        reg = PropertySchemeRegistry.instance()
        reg.register_widget("light", "light_a", _factory("a"))
        reg.register_widget("light", "light_b", _factory("b"))
        widgets = reg.get_widgets_for_payload(
            "light", PropertyPayload(paths=[], scheme="light")
        )
        tags = [getattr(w, "tag", None) for w in widgets]
        assert "a" in tags
        assert "b" in tags

    def test_duplicate_name_in_same_scheme_raises(self):
        reg = PropertySchemeRegistry.instance()
        reg.register_widget("light", "light", _factory("a"))
        with pytest.raises(ValueError, match="already registered"):
            reg.register_widget("light", "light", _factory("b"))

    def test_same_name_different_schemes_allowed(self):
        """The uniqueness key is ``(scheme, name)`` — identical names
        under different schemes must not collide."""
        reg = PropertySchemeRegistry.instance()
        reg.register_widget("light", "shared", _factory("light_shared"))
        reg.register_widget(
            "camera", "shared", _factory("camera_shared")
        )
        light_tags = [
            getattr(w, "tag", None)
            for w in reg.get_widgets_for_payload(
                "light", PropertyPayload(paths=[], scheme="light")
            )
        ]
        camera_tags = [
            getattr(w, "tag", None)
            for w in reg.get_widgets_for_payload(
                "camera", PropertyPayload(paths=[], scheme="camera")
            )
        ]
        assert "light_shared" in light_tags
        assert "camera_shared" in camera_tags

    def test_factory_invoked_per_call(self):
        """Each :meth:`get_widgets_for_payload` call calls every
        registered factory fresh — so per-window state never shares
        across rebuilds of different windows."""
        reg = PropertySchemeRegistry.instance()
        reg.register_widget("light", "light", _factory("light"))
        a = reg.get_widgets_for_payload(
            "light", PropertyPayload(paths=[], scheme="light")
        )
        b = reg.get_widgets_for_payload(
            "light", PropertyPayload(paths=[], scheme="light")
        )
        light_a = next(w for w in a if getattr(w, "tag", "") == "light")
        light_b = next(w for w in b if getattr(w, "tag", "") == "light")
        assert light_a is not light_b


# ---------------------------------------------------------------------------
# Ordering — order, top_stack, registration
# ---------------------------------------------------------------------------


@pytest.fixture()
def clean_registry():
    """Reset the registry and drop the default :class:`AttributesWidget`.

    TestOrdering asserts exact tag lists — the default registration
    would add a tagless entry that complicates equality assertions.
    Unregistering the default keeps the test input scoped to the
    three factories the test itself registers.
    """
    PropertySchemeRegistry._reset_for_tests()
    reg = PropertySchemeRegistry.instance()
    reg._unregister_widget("default", "attributes")
    return reg


class TestOrdering:
    def test_registration_order_preserved_within_same_order(self, clean_registry):
        """The task's done-signal #2: registration order is preserved."""
        reg = clean_registry
        reg.register_widget("light", "first", _factory("first"))
        reg.register_widget("light", "second", _factory("second"))
        reg.register_widget("light", "third", _factory("third"))
        widgets = reg.get_widgets_for_payload(
            "light", PropertyPayload(paths=[], scheme="light")
        )
        tags = [getattr(w, "tag", None) for w in widgets]
        assert tags == ["first", "second", "third"]

    def test_lower_order_appears_first(self, clean_registry):
        reg = clean_registry
        reg.register_widget("light", "late", _factory("late"), order=200)
        reg.register_widget("light", "early", _factory("early"), order=50)
        widgets = reg.get_widgets_for_payload(
            "light", PropertyPayload(paths=[], scheme="light")
        )
        tags = [getattr(w, "tag", None) for w in widgets]
        assert tags == ["early", "late"]

    def test_top_stack_true_wins_tiebreak_at_same_order(self, clean_registry):
        """The task's done-signal #3: ``top_stack=True`` widgets appear
        before others at the same ``order``."""
        reg = clean_registry
        # Register the non-top_stack entry FIRST — if top_stack didn't
        # override registration order, ``a`` would come first.
        reg.register_widget("light", "a", _factory("a"), order=100)
        reg.register_widget(
            "light", "b_top", _factory("b_top"), order=100, top_stack=True
        )
        widgets = reg.get_widgets_for_payload(
            "light", PropertyPayload(paths=[], scheme="light")
        )
        tags = [getattr(w, "tag", None) for w in widgets]
        assert tags == ["b_top", "a"]

    def test_top_stack_does_not_override_lower_order(self, clean_registry):
        """``top_stack`` is a tiebreak at equal ``order``, not a global
        override — a ``top_stack=True`` entry with ``order=200`` still
        sorts below a ``top_stack=False`` entry with ``order=50``."""
        reg = clean_registry
        reg.register_widget(
            "light", "top_high", _factory("top_high"),
            order=200, top_stack=True,
        )
        reg.register_widget("light", "low", _factory("low"), order=50)
        widgets = reg.get_widgets_for_payload(
            "light", PropertyPayload(paths=[], scheme="light")
        )
        tags = [getattr(w, "tag", None) for w in widgets]
        assert tags == ["low", "top_high"]

    def test_default_scheme_widgets_merge_with_scheme_specific(self):
        """Widgets registered for ``"default"`` and for ``"light"`` are
        merged into one sorted list — the merge honours ``order`` across
        schemes rather than grouping by scheme. ``first_ever`` (order
        10, default) beats both the default-scheme
        :class:`AttributesWidget` (order 100) and the ``light_mid``
        entry (order 50); the :class:`AttributesWidget` lands last.
        """
        reg = PropertySchemeRegistry.instance()
        reg.register_widget(
            "default", "first_ever", _factory("first_ever"), order=10,
        )
        reg.register_widget(
            "light", "light_mid", _factory("light_mid"), order=50,
        )
        widgets = reg.get_widgets_for_payload(
            "light", PropertyPayload(paths=[], scheme="light")
        )
        # Assert exact ordering by class / tag. The last entry is the
        # module-import :class:`AttributesWidget`; the first two are
        # the test-registered recording widgets, asserted by tag.
        assert len(widgets) == 3
        assert getattr(widgets[0], "tag", None) == "first_ever"
        assert getattr(widgets[1], "tag", None) == "light_mid"
        assert isinstance(widgets[2], AttributesWidget)


# ---------------------------------------------------------------------------
# Subscription cancel
# ---------------------------------------------------------------------------


class TestSubscriptionCancel:
    def test_cancel_removes_widget(self):
        """The task's done-signal #4: ``Subscription.cancel`` removes
        the widget from future :meth:`get_widgets_for_payload` calls."""
        reg = PropertySchemeRegistry.instance()
        sub = reg.register_widget("light", "light", _factory("light"))
        assert any(
            getattr(w, "tag", None) == "light"
            for w in reg.get_widgets_for_payload(
                "light", PropertyPayload(paths=[], scheme="light")
            )
        )
        sub.cancel()
        assert not any(
            getattr(w, "tag", None) == "light"
            for w in reg.get_widgets_for_payload(
                "light", PropertyPayload(paths=[], scheme="light")
            )
        )

    def test_cancel_is_idempotent(self):
        reg = PropertySchemeRegistry.instance()
        sub = reg.register_widget("light", "light", _factory("light"))
        sub.cancel()
        sub.cancel()  # must not raise

    def test_cancel_does_not_affect_other_scheme(self):
        reg = PropertySchemeRegistry.instance()
        sub_light = reg.register_widget("light", "x", _factory("light_x"))
        reg.register_widget("camera", "x", _factory("camera_x"))
        sub_light.cancel()
        camera_tags = [
            getattr(w, "tag", None)
            for w in reg.get_widgets_for_payload(
                "camera", PropertyPayload(paths=[], scheme="camera")
            )
        ]
        assert "camera_x" in camera_tags

    def test_cancel_does_not_evict_replacement(self):
        """After ``sub.cancel()`` + re-register + repeat cancel, the
        replacement registration is not dropped — cancel only removes
        the specific ``(scheme, name)`` it was issued for, and only
        does so once."""
        reg = PropertySchemeRegistry.instance()
        sub = reg.register_widget("light", "x", _factory("first"))
        sub.cancel()
        # Re-register under the same name — must succeed because the
        # prior registration was cancelled.
        reg.register_widget("light", "x", _factory("second"))
        # A second cancel on the original handle is a no-op and must
        # not evict the replacement.
        sub.cancel()
        tags = [
            getattr(w, "tag", None)
            for w in reg.get_widgets_for_payload(
                "light", PropertyPayload(paths=[], scheme="light")
            )
        ]
        assert "second" in tags


# ---------------------------------------------------------------------------
# register_scheme_delegate — Step 6.5 scope: registration + cancel only.
# Step 6.6 wires the actual delegate dispatch into get_widgets_for_payload.
# ---------------------------------------------------------------------------


class _StubDelegate:
    """Minimal delegate placeholder — Step 6.5 only stores the record."""


class TestRegisterSchemeDelegate:
    def test_register_returns_subscription(self):
        reg = PropertySchemeRegistry.instance()
        sub = reg.register_scheme_delegate("prim", "stub", _StubDelegate())
        assert hasattr(sub, "cancel")

    def test_duplicate_delegate_name_raises(self):
        reg = PropertySchemeRegistry.instance()
        reg.register_scheme_delegate("prim", "stub", _StubDelegate())
        with pytest.raises(ValueError, match="already registered"):
            reg.register_scheme_delegate("prim", "stub", _StubDelegate())

    def test_delegate_cancel_removes_from_registry(self):
        reg = PropertySchemeRegistry.instance()
        sub = reg.register_scheme_delegate("prim", "stub", _StubDelegate())
        sub.cancel()
        # After cancel, a re-register under the same name must succeed.
        reg.register_scheme_delegate("prim", "stub", _StubDelegate())

    def test_delegate_cancel_idempotent(self):
        reg = PropertySchemeRegistry.instance()
        sub = reg.register_scheme_delegate("prim", "stub", _StubDelegate())
        sub.cancel()
        sub.cancel()  # must not raise


# ---------------------------------------------------------------------------
# PropertyWindow integration — the pseudo-code from the task lands here
# ---------------------------------------------------------------------------


def _two_group_adapter():
    """Small adapter the integration test queries through rebuild."""
    from ovui_data_adapters.common import AttributeMetadata

    from ovui_widgets.common.testing.mock_property import MockPropertyAdapter
    attrs = {
        "x": AttributeMetadata(
            name="x", display_name="X", type_name="float",
            value_type=float, group="Transform",
        ),
    }
    adapter = MockPropertyAdapter(paths=["/World/Sphere"], attributes=attrs)
    adapter.set_value("x", 1.0)
    return adapter


class _FakeVStack:
    """Stand-in for ``ui.VStack`` — ``clear`` + context-manager only."""
    def clear(self) -> None: ...
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _make_headless_window():
    """Construct a :class:`PropertyWindow` bypassing ``ManagedWindow.__init__``.

    Mirrors the helper used in ``test_attributes_widget.py`` — the
    ``PropertyWindow()`` constructor opens a real ``ui.Window`` which
    needs an active frame scope; the bypass lets rebuild logic run
    headless.
    """
    from ovui_widgets.property.widget.attributes_widget import AttributesWidget
    from ovui_widgets.property.window import PropertyWindow
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
    w._widgets = []
    w._default_attributes = AttributesWidget(w)
    # Step 7.3: ``_rebuild_content`` guards on these two fields; bypass-
    # ``__init__`` tests seed them as the no-op sentinels so the
    # preserver branch short-circuits without raising.
    w._scroll_frame = None
    w._scroll_preserver = None
    return w


class TestPropertyWindowIntegration:
    def test_rebuild_queries_registry_for_default_scheme(self, monkeypatch):
        """:meth:`PropertyWindow._rebuild_content` asks the registry
        for the widget list keyed on the payload's scheme (default here
        because :class:`PropertyPayload` defaults to ``"default"``).
        The registry's :class:`AttributesWidget` factory is invoked
        and its :meth:`build_items` fires."""
        calls: List[int] = []
        monkeypatch.setattr(
            AttributesWidget, "build_items",
            lambda self: calls.append(1),
        )
        w = _make_headless_window()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        w._content = _FakeVStack()
        w._rebuild_content()
        assert calls == [1]

    def test_rebuild_injects_window_on_attributes_widget(self, monkeypatch):
        """Registry-produced :class:`AttributesWidget` instances are
        windowless on construction;
        :meth:`PropertyWindow._build_registered_widgets` binds the
        window via :meth:`AttributesWidget.set_window` before invoking
        :meth:`on_new_payload` so the subsequent build has adapter /
        selection / filter state."""
        bound_windows: List[Any] = []
        real_set_window = AttributesWidget.set_window

        def _record_set_window(self, window):
            bound_windows.append(window)
            real_set_window(self, window)

        monkeypatch.setattr(AttributesWidget, "set_window", _record_set_window)
        monkeypatch.setattr(
            AttributesWidget, "build_items", lambda self: None,
        )
        w = _make_headless_window()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        w._content = _FakeVStack()
        w._rebuild_content()
        assert w in bound_windows

    def test_additional_scheme_widget_also_builds(self, monkeypatch):
        """Register a second widget for a non-default scheme; advance
        ``payload.get_scheme()`` to match; the window builds both the
        default :class:`AttributesWidget` and the new widget on rebuild."""
        attr_builds: List[int] = []
        extra_builds: List[int] = []
        monkeypatch.setattr(
            AttributesWidget, "build_items",
            lambda self: attr_builds.append(1),
        )

        class _LightWidget(PropertyWidget):
            def on_new_payload(self, payload: PropertyPayload) -> bool:
                return True
            def build_items(self) -> None:
                extra_builds.append(1)

        PropertySchemeRegistry.instance().register_widget(
            "light", "light_widget", _LightWidget
        )

        # Force the window to build under the ``"light"`` scheme by
        # stubbing :class:`PropertyPayload.get_scheme` — the window
        # does not expose a scheme setter in Step 6.5 (that happens
        # when the adapter supplies the scheme in later steps).
        monkeypatch.setattr(
            PropertyPayload, "get_scheme", lambda self: "light"
        )

        w = _make_headless_window()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        w._content = _FakeVStack()
        w._rebuild_content()
        assert attr_builds == [1]
        assert extra_builds == [1]

    def test_on_new_payload_false_suppresses_build(self, monkeypatch):
        """A widget whose :meth:`on_new_payload` returns ``False`` is
        skipped — :meth:`build_items` never runs for it."""
        monkeypatch.setattr(
            AttributesWidget, "build_items",
            lambda self: None,
        )
        built: List[int] = []

        class _RefusingWidget(PropertyWidget):
            def on_new_payload(self, payload: PropertyPayload) -> bool:
                return False
            def build_items(self) -> None:
                built.append(1)

        PropertySchemeRegistry.instance().register_widget(
            "default", "refusing", _RefusingWidget
        )
        w = _make_headless_window()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        w._content = _FakeVStack()
        w._rebuild_content()
        assert built == []
