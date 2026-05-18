# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 6.6 — :class:`PropertySchemeDelegate`.

Covers the the property inspector step 6.6 done-signal checklist:

* :class:`PropertySchemeDelegate` ABC is importable from the widget
  subpackage and from its concrete module.
* Both :meth:`get_widgets` and :meth:`get_unwanted_widgets` are
  abstract — instantiating the ABC directly raises ``TypeError``;
  subclasses that omit either method cannot be constructed.
* :meth:`PropertySchemeRegistry.get_widgets_for_payload` runs every
  delegate registered for the target scheme (plus ``"default"``
  delegates for universality) on every call.
* Two delegates returning overlapping wanted lists both contribute —
  a widget named by either survives.
* A widget named in any delegate's :meth:`get_unwanted_widgets` is
  removed from the result.
* A widget named in one delegate's ``unwanted`` but also in another
  delegate's :meth:`get_widgets` survives (wanted wins over
  unwanted).
* Delegate :class:`_DelegateSubscription` :meth:`cancel` removes the
  delegate from future :meth:`get_widgets_for_payload` calls.
* Widgets not mentioned by any delegate are unaffected — when no
  delegates exist the registry reduces to Step 6.5 behaviour.
* Sort order is preserved after delegate filtering (drops in place,
  no re-sort).

Every test that touches the singleton resets it at setup / teardown
so one test's registrations never leak into another's assertions.
"""

from __future__ import annotations

from typing import List

import pytest

from ovwidgets.property.payload import PropertyPayload
from ovwidgets.property.widget import (
    AttributesWidget,
    PropertySchemeDelegate,
    PropertySchemeRegistry,
    PropertyWidget,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _TaggedWidget(PropertyWidget):
    """Minimal :class:`PropertyWidget` carrying a tag for identification.

    Tests assert which factories fired by reading the returned
    widgets' ``tag`` attribute.
    """

    def __init__(self, tag: str = "w") -> None:
        self.tag = tag

    def on_new_payload(self, payload: PropertyPayload) -> bool:
        return True

    def build_items(self) -> None:
        pass


def _factory(tag: str):
    """Zero-arg factory producing a fresh :class:`_TaggedWidget`."""
    def _build() -> _TaggedWidget:
        return _TaggedWidget(tag=tag)
    return _build


class _ListDelegate(PropertySchemeDelegate):
    """Constant-list delegate — returns the pair it was constructed with.

    Both :meth:`get_widgets` and :meth:`get_unwanted_widgets` ignore
    the payload argument and return the stored lists; this keeps the
    delegate deterministic so filter assertions are self-contained.
    """

    def __init__(
        self,
        wanted: List[str] | None = None,
        unwanted: List[str] | None = None,
    ) -> None:
        self._wanted = list(wanted or [])
        self._unwanted = list(unwanted or [])
        self.get_widgets_calls: List[PropertyPayload] = []
        self.get_unwanted_calls: List[PropertyPayload] = []

    def get_widgets(self, payload: PropertyPayload) -> List[str]:
        self.get_widgets_calls.append(payload)
        return list(self._wanted)

    def get_unwanted_widgets(self, payload: PropertyPayload) -> List[str]:
        self.get_unwanted_calls.append(payload)
        return list(self._unwanted)


@pytest.fixture(autouse=True)
def _reset_registry_between_tests():
    """Reset the singleton before and after every test.

    Rebuilding the singleton re-runs ``_register_defaults`` so each
    test observes the baseline ``"default"`` → :class:`AttributesWidget`
    mapping regardless of churn elsewhere in the suite.
    """
    PropertySchemeRegistry._reset_for_tests()
    yield
    PropertySchemeRegistry._reset_for_tests()


@pytest.fixture()
def clean_registry():
    """Reset the registry and drop the default :class:`AttributesWidget`.

    Tests that assert exact tag lists don't want the module-import
    registration in the picture. The default is re-registered at the
    next singleton construction, so dropping it here only affects
    the current test.
    """
    PropertySchemeRegistry._reset_for_tests()
    reg = PropertySchemeRegistry.instance()
    reg._unregister_widget("default", "attributes")
    return reg


# ---------------------------------------------------------------------------
# ABC shape
# ---------------------------------------------------------------------------


class TestImportShape:
    def test_importable_from_widget_subpackage(self):
        from ovwidgets.property.widget import PropertySchemeDelegate as D
        assert D is not None

    def test_importable_from_direct_module(self):
        from ovwidgets.property.widget.scheme_delegate import PropertySchemeDelegate as D
        assert D is not None

    def test_re_export_identity(self):
        from ovwidgets.property.widget import PropertySchemeDelegate as A
        from ovwidgets.property.widget.scheme_delegate import (
            PropertySchemeDelegate as B,
        )
        assert A is B

    def test_in_widget_subpackage_all(self):
        import ovwidgets.property.widget as w_mod
        assert "PropertySchemeDelegate" in w_mod.__all__


class TestAbstractContract:
    def test_both_methods_are_abstract(self):
        assert PropertySchemeDelegate.__abstractmethods__ == frozenset(
            {"get_widgets", "get_unwanted_widgets"}
        )

    def test_cannot_instantiate_base_class(self):
        with pytest.raises(TypeError, match="abstract"):
            PropertySchemeDelegate()  # type: ignore[abstract]

    def test_subclass_without_get_widgets_cannot_instantiate(self):
        class _Bad(PropertySchemeDelegate):
            def get_unwanted_widgets(self, payload):
                return []

        with pytest.raises(TypeError, match="abstract"):
            _Bad()  # type: ignore[abstract]

    def test_subclass_without_get_unwanted_widgets_cannot_instantiate(self):
        class _Bad(PropertySchemeDelegate):
            def get_widgets(self, payload):
                return []

        with pytest.raises(TypeError, match="abstract"):
            _Bad()  # type: ignore[abstract]

    def test_complete_subclass_instantiable(self):
        d = _ListDelegate(wanted=["a"], unwanted=["b"])
        payload = PropertyPayload(paths=[])
        assert d.get_widgets(payload) == ["a"]
        assert d.get_unwanted_widgets(payload) == ["b"]


# ---------------------------------------------------------------------------
# Delegate dispatch inside :meth:`get_widgets_for_payload`
# ---------------------------------------------------------------------------


class TestDelegateDispatchInvokedPerCall:
    def test_delegate_methods_called_with_payload(self, clean_registry):
        """The registry runs every delegate's
        :meth:`get_widgets` / :meth:`get_unwanted_widgets` once per
        :meth:`get_widgets_for_payload` call, threading the caller's
        payload unmodified."""
        reg = clean_registry
        reg.register_widget("prim", "a", _factory("a"))

        d = _ListDelegate(wanted=["a"])
        reg.register_scheme_delegate("prim", "d", d)

        payload = PropertyPayload(paths=["/World/Sphere"], scheme="prim")
        reg.get_widgets_for_payload("prim", payload)

        assert d.get_widgets_calls == [payload]
        assert d.get_unwanted_calls == [payload]

    def test_delegate_methods_called_each_rebuild(self, clean_registry):
        """Repeated calls invoke the delegate fresh every time — so a
        payload-sensitive delegate can produce different answers on
        successive rebuilds."""
        reg = clean_registry
        reg.register_widget("prim", "a", _factory("a"))

        d = _ListDelegate(wanted=["a"])
        reg.register_scheme_delegate("prim", "d", d)

        payload = PropertyPayload(paths=[], scheme="prim")
        reg.get_widgets_for_payload("prim", payload)
        reg.get_widgets_for_payload("prim", payload)
        reg.get_widgets_for_payload("prim", payload)

        assert len(d.get_widgets_calls) == 3
        assert len(d.get_unwanted_calls) == 3


class TestNoDelegatesIsNoOp:
    def test_no_delegates_preserves_step65_behaviour(self):
        """When no delegates are registered, the registry returns the
        full registered-widget list — Step 6.5's catch-all survives.
        The module-import :class:`AttributesWidget` is present."""
        reg = PropertySchemeRegistry.instance()
        widgets = reg.get_widgets_for_payload(
            "default", PropertyPayload(paths=[])
        )
        assert any(isinstance(w, AttributesWidget) for w in widgets)

    def test_widgets_not_mentioned_by_delegates_survive(self, clean_registry):
        """A widget no delegate mentions is neither wanted nor unwanted
        — the filter condition ``name in wanted or name not in unwanted``
        evaluates True for it, so it passes through unchanged."""
        reg = clean_registry
        reg.register_widget("prim", "a", _factory("a"))
        reg.register_widget("prim", "b", _factory("b"))
        reg.register_widget("prim", "c", _factory("c"))

        # Delegate mentions only "a" in wanted — b and c are untouched.
        reg.register_scheme_delegate(
            "prim", "d", _ListDelegate(wanted=["a"])
        )
        widgets = reg.get_widgets_for_payload(
            "prim", PropertyPayload(paths=[], scheme="prim")
        )
        tags = [getattr(w, "tag", None) for w in widgets]
        assert tags == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Task done-signal tests — the four cases the step spec calls out
# ---------------------------------------------------------------------------


class TestTwoDelegatesUnionWanted:
    def test_two_delegates_both_contribute_overlapping_lists(
        self, clean_registry,
    ):
        """Task done-signal #1: register two delegates returning
        overlapping widget lists — both contribute their widgets."""
        reg = clean_registry
        reg.register_widget("prim", "a", _factory("a"))
        reg.register_widget("prim", "b", _factory("b"))
        reg.register_widget("prim", "c", _factory("c"))

        # Two delegates whose wanted lists overlap on "b".
        reg.register_scheme_delegate(
            "prim", "d1", _ListDelegate(wanted=["a", "b"])
        )
        reg.register_scheme_delegate(
            "prim", "d2", _ListDelegate(wanted=["b", "c"])
        )
        widgets = reg.get_widgets_for_payload(
            "prim", PropertyPayload(paths=[], scheme="prim")
        )
        tags = [getattr(w, "tag", None) for w in widgets]
        # All three survive — b is named twice but only appears once
        # (the registry iterates the candidate list in sort order, not
        # the wanted set).
        assert tags == ["a", "b", "c"]


class TestUnwantedRemovesWidget:
    def test_unwanted_widget_removed(self, clean_registry):
        """Task done-signal #2: a widget named in a delegate's
        ``unwanted`` list is removed from the result."""
        reg = clean_registry
        reg.register_widget("prim", "a", _factory("a"))
        reg.register_widget("prim", "b", _factory("b"))
        reg.register_widget("prim", "c", _factory("c"))

        # Delegate hides "b".
        reg.register_scheme_delegate(
            "prim", "d", _ListDelegate(unwanted=["b"])
        )
        widgets = reg.get_widgets_for_payload(
            "prim", PropertyPayload(paths=[], scheme="prim")
        )
        tags = [getattr(w, "tag", None) for w in widgets]
        assert tags == ["a", "c"]

    def test_unwanted_unknown_name_is_silently_ignored(self, clean_registry):
        """A name in ``unwanted`` that doesn't match any registered
        widget is a no-op — the candidate list is unchanged."""
        reg = clean_registry
        reg.register_widget("prim", "a", _factory("a"))

        reg.register_scheme_delegate(
            "prim", "d", _ListDelegate(unwanted=["does_not_exist"])
        )
        widgets = reg.get_widgets_for_payload(
            "prim", PropertyPayload(paths=[], scheme="prim")
        )
        tags = [getattr(w, "tag", None) for w in widgets]
        assert tags == ["a"]


class TestWantedBeatsUnwanted:
    def test_widget_wanted_by_one_unwanted_by_another_survives(
        self, clean_registry,
    ):
        """Task done-signal #3: a widget in one delegate's ``unwanted``
        but another's ``wanted`` list survives — wanted wins."""
        reg = clean_registry
        reg.register_widget("prim", "a", _factory("a"))
        reg.register_widget("prim", "b", _factory("b"))
        reg.register_widget("prim", "c", _factory("c"))

        # d1 wants "b"; d2 wants it unwanted. Wanted must win.
        reg.register_scheme_delegate(
            "prim", "d1", _ListDelegate(wanted=["b"])
        )
        reg.register_scheme_delegate(
            "prim", "d2", _ListDelegate(unwanted=["b"])
        )
        widgets = reg.get_widgets_for_payload(
            "prim", PropertyPayload(paths=[], scheme="prim")
        )
        tags = [getattr(w, "tag", None) for w in widgets]
        assert tags == ["a", "b", "c"]

    def test_widget_wanted_and_unwanted_by_same_delegate_survives(
        self, clean_registry,
    ):
        """Edge case: a single delegate names the same widget in both
        lists — wanted still wins (same precedence rule, applied
        within a delegate rather than across delegates)."""
        reg = clean_registry
        reg.register_widget("prim", "a", _factory("a"))
        reg.register_widget("prim", "b", _factory("b"))

        reg.register_scheme_delegate(
            "prim", "d", _ListDelegate(wanted=["b"], unwanted=["b"])
        )
        widgets = reg.get_widgets_for_payload(
            "prim", PropertyPayload(paths=[], scheme="prim")
        )
        tags = [getattr(w, "tag", None) for w in widgets]
        assert tags == ["a", "b"]


class TestDelegateSubscriptionCancel:
    def test_cancel_removes_delegate_from_dispatch(self, clean_registry):
        """Task done-signal #4: after cancel, the delegate stops
        contributing to filtering — previously unwanted widgets
        reappear."""
        reg = clean_registry
        reg.register_widget("prim", "a", _factory("a"))
        reg.register_widget("prim", "b", _factory("b"))

        sub = reg.register_scheme_delegate(
            "prim", "d", _ListDelegate(unwanted=["b"])
        )

        # Pre-cancel: b is hidden.
        widgets = reg.get_widgets_for_payload(
            "prim", PropertyPayload(paths=[], scheme="prim")
        )
        assert [getattr(w, "tag", None) for w in widgets] == ["a"]

        # Post-cancel: b reappears.
        sub.cancel()
        widgets = reg.get_widgets_for_payload(
            "prim", PropertyPayload(paths=[], scheme="prim")
        )
        assert [getattr(w, "tag", None) for w in widgets] == ["a", "b"]

    def test_cancel_only_removes_the_cancelled_delegate(self, clean_registry):
        """After one delegate is cancelled, others still contribute —
        the cancellation is scoped to its ``(scheme, name)`` handle."""
        reg = clean_registry
        reg.register_widget("prim", "a", _factory("a"))
        reg.register_widget("prim", "b", _factory("b"))
        reg.register_widget("prim", "c", _factory("c"))

        sub1 = reg.register_scheme_delegate(
            "prim", "d1", _ListDelegate(unwanted=["b"])
        )
        reg.register_scheme_delegate(
            "prim", "d2", _ListDelegate(unwanted=["c"])
        )

        # Both delegates contributing: only "a" survives.
        widgets = reg.get_widgets_for_payload(
            "prim", PropertyPayload(paths=[], scheme="prim")
        )
        assert [getattr(w, "tag", None) for w in widgets] == ["a"]

        # Cancel d1 — d2 still hides "c" but b reappears.
        sub1.cancel()
        widgets = reg.get_widgets_for_payload(
            "prim", PropertyPayload(paths=[], scheme="prim")
        )
        assert [getattr(w, "tag", None) for w in widgets] == ["a", "b"]


# ---------------------------------------------------------------------------
# Cross-scheme / universality semantics
# ---------------------------------------------------------------------------


class TestDefaultSchemeDelegateIsUniversal:
    def test_default_scheme_delegate_applies_to_other_schemes(
        self, clean_registry,
    ):
        """Delegates registered under ``"default"`` are consulted for
        every scheme — mirroring how default widgets surface for every
        payload. This keeps the API self-similar across the two
        registration tables."""
        reg = clean_registry
        reg.register_widget("prim", "a", _factory("a"))
        reg.register_widget("prim", "b", _factory("b"))

        # Default-scheme delegate hides "b" universally.
        reg.register_scheme_delegate(
            "default", "global_hide", _ListDelegate(unwanted=["b"])
        )
        widgets = reg.get_widgets_for_payload(
            "prim", PropertyPayload(paths=[], scheme="prim")
        )
        tags = [getattr(w, "tag", None) for w in widgets]
        assert tags == ["a"]

    def test_scheme_delegate_does_not_affect_other_schemes(
        self, clean_registry,
    ):
        """A delegate registered for a specific scheme only affects
        that scheme's query — Step 6.5's scheme isolation holds."""
        reg = clean_registry
        reg.register_widget("prim", "a", _factory("prim_a"))
        reg.register_widget("light", "a", _factory("light_a"))

        reg.register_scheme_delegate(
            "prim", "d", _ListDelegate(unwanted=["a"])
        )

        # Light query is unaffected.
        widgets = reg.get_widgets_for_payload(
            "light", PropertyPayload(paths=[], scheme="light")
        )
        tags = [getattr(w, "tag", None) for w in widgets]
        assert "light_a" in tags

        # Prim query hides "a".
        widgets = reg.get_widgets_for_payload(
            "prim", PropertyPayload(paths=[], scheme="prim")
        )
        tags = [getattr(w, "tag", None) for w in widgets]
        assert tags == []


# ---------------------------------------------------------------------------
# Sort-order preservation after delegate filtering
# ---------------------------------------------------------------------------


class TestOrderingPreservedAfterFiltering:
    def test_filtered_result_preserves_order(self, clean_registry):
        """The registry filters the already-sorted candidate list in
        place — survivors run in the same order they would without
        delegates."""
        reg = clean_registry
        # Register three widgets with different ``order`` so the sort
        # key determines the sequence, not registration order.
        reg.register_widget("prim", "late", _factory("late"), order=300)
        reg.register_widget("prim", "mid", _factory("mid"), order=200)
        reg.register_widget("prim", "early", _factory("early"), order=100)

        # Hide the middle entry; the survivors must stay in sort order.
        reg.register_scheme_delegate(
            "prim", "d", _ListDelegate(unwanted=["mid"])
        )
        widgets = reg.get_widgets_for_payload(
            "prim", PropertyPayload(paths=[], scheme="prim")
        )
        tags = [getattr(w, "tag", None) for w in widgets]
        assert tags == ["early", "late"]

    def test_top_stack_tiebreak_still_honoured(self, clean_registry):
        """Delegate filtering runs after the sort, so ``top_stack``
        ordering survives the filter step — a top-stack entry named
        by a wanted delegate stays at the top of its ``order`` bucket.
        """
        reg = clean_registry
        reg.register_widget(
            "prim", "a", _factory("a"), order=100,
        )
        reg.register_widget(
            "prim", "b_top", _factory("b_top"),
            order=100, top_stack=True,
        )
        reg.register_widget(
            "prim", "c", _factory("c"), order=100,
        )

        reg.register_scheme_delegate(
            "prim", "d", _ListDelegate(unwanted=["c"])
        )
        widgets = reg.get_widgets_for_payload(
            "prim", PropertyPayload(paths=[], scheme="prim")
        )
        tags = [getattr(w, "tag", None) for w in widgets]
        # b_top still wins the tiebreak; c is hidden; a remains.
        assert tags == ["b_top", "a"]


# ---------------------------------------------------------------------------
# Registry-window integration — sanity check that the delegate filter
# flows through :meth:`PropertyWindow._rebuild_content`
# ---------------------------------------------------------------------------


def _two_group_adapter():
    """Lightweight adapter for the registry → window integration test."""
    from ovui_data_adapters.common import AttributeMetadata

    from ovwidgets.common.testing.mock_property import MockPropertyAdapter
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
    def clear(self) -> None: ...
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _make_headless_window():
    """Construct a :class:`PropertyWindow` bypassing ``ManagedWindow.__init__``.

    Mirrors the helper used in the rest of the test suite — the real
    constructor opens a ``ui.Window`` that needs a live frame scope.
    """
    from ovwidgets.property.widget.attributes_widget import AttributesWidget
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
    w._widgets = []
    w._default_attributes = AttributesWidget(w)
    # Step 7.3: ``_rebuild_content`` guards on these two fields; bypass-
    # ``__init__`` tests seed them as the no-op sentinels so the
    # preserver branch short-circuits without raising.
    w._scroll_frame = None
    w._scroll_preserver = None
    return w


class TestPropertyWindowIntegration:
    def test_delegate_suppresses_widget_through_window_rebuild(
        self, monkeypatch,
    ):
        """A delegate hiding ``"attributes"`` prevents the registry
        from producing an :class:`AttributesWidget` — the window's
        subsequent rebuild never calls :meth:`build_items` on one."""
        built: List[int] = []
        monkeypatch.setattr(
            AttributesWidget, "build_items",
            lambda self: built.append(1),
        )

        PropertySchemeRegistry.instance().register_scheme_delegate(
            "default", "hide_attrs",
            _ListDelegate(unwanted=["attributes"]),
        )

        w = _make_headless_window()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        w._content = _FakeVStack()
        w._rebuild_content()
        assert built == []

    def test_wanted_delegate_keeps_widget_through_window_rebuild(
        self, monkeypatch,
    ):
        """Baseline: with a wanted delegate naming ``"attributes"``,
        :class:`AttributesWidget` still builds. This pins the happy
        path for the wanted-wins precedence rule (no override means
        wanted alone is enough)."""
        built: List[int] = []
        monkeypatch.setattr(
            AttributesWidget, "build_items",
            lambda self: built.append(1),
        )

        PropertySchemeRegistry.instance().register_scheme_delegate(
            "default", "want_attrs",
            _ListDelegate(wanted=["attributes"]),
        )

        w = _make_headless_window()
        w._adapter = _two_group_adapter()
        w._selection = ["/World/Sphere"]
        w._content = _FakeVStack()
        w._rebuild_content()
        assert built == [1]
