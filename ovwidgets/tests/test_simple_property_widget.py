# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 6.3 — :class:`SimplePropertyWidget` convenience base.

Covers the task's Step 6.3 done-signal checklist:

* :class:`SimplePropertyWidget` is instantiable with a title
* :class:`ui.CollapsableFrame` is created with the title passed to the
  constructor (when the title is non-empty)
* :meth:`request_rebuild` schedules a rebuild via
  :meth:`Application.call_later` and coalesces back-to-back calls
* :meth:`subscribe_filter` wires a model's ``add_value_changed_fn`` so
  filter-text changes fire :meth:`request_rebuild`
* :meth:`add_item` / :meth:`add_item_with_model` emit their builder
  inside the content ``VStack`` (or ambient scope if no frame)
* Subclasses can override :meth:`build_items` or
  :meth:`build_items_content`
* :class:`AttributesWidget` is a :class:`SimplePropertyWidget` subclass
  after the Step 6.3 rebase
* :meth:`destroy` cancels the pending rebuild and removes the filter
  subscription — idempotent and safe on a never-built widget
"""

from __future__ import annotations

from typing import Any, List

import omni.ui as ui
import pytest

# ---------------------------------------------------------------------------
# Helpers — fake ovui primitives + fake Application singleton
# ---------------------------------------------------------------------------


class _FakeFrame:
    """Recording double for :class:`ui.CollapsableFrame`.

    Captures the constructor kwargs so tests can assert title /
    collapse state. ``__enter__`` / ``__exit__`` make it compatible
    with ``with`` so :meth:`SimplePropertyWidget.build_items` can run
    end-to-end under the monkeypatch.
    """

    instances: List["_FakeFrame"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.rebuild_calls = 0
        _FakeFrame.instances.append(self)

    def __enter__(self) -> "_FakeFrame":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def rebuild(self) -> None:
        self.rebuild_calls += 1


class _FakeVStack:
    """Recording double for :class:`ui.VStack` — mirrors :class:`_FakeFrame`."""

    instances: List["_FakeVStack"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.children: List[Any] = []
        self.enter_count = 0
        self.exit_count = 0
        _FakeVStack.instances.append(self)

    def __enter__(self) -> "_FakeVStack":
        self.enter_count += 1
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.exit_count += 1
        return False


@pytest.fixture()
def fake_ui(monkeypatch):
    """Patch :class:`ui.CollapsableFrame` + :class:`ui.VStack` with doubles."""
    _FakeFrame.instances = []
    _FakeVStack.instances = []
    monkeypatch.setattr(ui, "CollapsableFrame", _FakeFrame)
    monkeypatch.setattr(ui, "VStack", _FakeVStack)
    return (_FakeFrame, _FakeVStack)


class _FakeHandle:
    """Recording double for :class:`ovwidgets.app.application.CallbackHandle`."""

    def __init__(self, callback: Any) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _FakeApp:
    """Stand-in for :class:`ovwidgets.app.application.Application` with a ``call_later``."""

    def __init__(self) -> None:
        self.scheduled: List[_FakeHandle] = []

    def call_later(self, delay: float, callback: Any) -> _FakeHandle:
        self.scheduled.append(_FakeHandle(callback))
        self.scheduled[-1].delay = delay  # type: ignore[attr-defined]
        return self.scheduled[-1]


@pytest.fixture()
def fake_app(monkeypatch):
    """Install a fake :class:`Application` singleton that records ``call_later``.

    Also registers the fake's ``call_later`` with
    :func:`ovwidgets.common.scheduler.set_call_later` so widget code that
    routes through ``common.scheduler.call_later`` (Rev 8 §5.5; Step 5)
    reaches the same fake. Both the legacy ``Application._instance``
    monkey-patch and the ``common.scheduler`` backend are restored on
    teardown.
    """
    from ovwidgets.app.application import Application
    from ovwidgets.common import scheduler as _scheduler
    prior_instance = Application._instance
    prior_call_later_fn = _scheduler._call_later_fn
    app = _FakeApp()
    monkeypatch.setattr(Application, "_instance", app)
    _scheduler.set_call_later(app.call_later)
    yield app
    Application._instance = prior_instance
    _scheduler.set_call_later(prior_call_later_fn)


class _FakeModel:
    """Recording double for :class:`ui.AbstractValueModel`.

    ``add_value_changed_fn`` returns an int id; ``remove_value_changed_fn``
    takes that id. ``fire()`` invokes every live callback (simulating a
    value change from the ovui side).
    """

    def __init__(self) -> None:
        self._next_id = 0
        self._callbacks: dict = {}
        self.remove_calls: List[int] = []

    def add_value_changed_fn(self, fn: Any) -> int:
        sub_id = self._next_id
        self._next_id += 1
        self._callbacks[sub_id] = fn
        return sub_id

    def remove_value_changed_fn(self, sub_id: int) -> None:
        self.remove_calls.append(sub_id)
        self._callbacks.pop(sub_id, None)

    def fire(self) -> None:
        for fn in list(self._callbacks.values()):
            fn(self)

    @property
    def live_subscriptions(self) -> int:
        return len(self._callbacks)


# ---------------------------------------------------------------------------
# Module / import shape
# ---------------------------------------------------------------------------


class TestSimplePropertyWidgetImportShape:
    def test_importable_from_subpackage(self):
        from ovwidgets.property.widget import SimplePropertyWidget
        assert SimplePropertyWidget is not None

    def test_importable_from_direct_module(self):
        from ovwidgets.property.widget.simple_property_widget import SimplePropertyWidget
        assert SimplePropertyWidget is not None

    def test_re_export_identity(self):
        from ovwidgets.property.widget import SimplePropertyWidget as A
        from ovwidgets.property.widget.simple_property_widget import SimplePropertyWidget as B
        assert A is B

    def test_in_widget_subpackage_all(self):
        import ovwidgets.property.widget as w_mod
        assert "SimplePropertyWidget" in w_mod.__all__

    def test_is_property_widget_subclass(self):
        from ovwidgets.property.widget import PropertyWidget, SimplePropertyWidget
        assert issubclass(SimplePropertyWidget, PropertyWidget)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_instantiable_with_title(self):
        """Required by the Step 6.3 done-signal: SimplePropertyWidget is
        instantiable with a title."""
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Transform")
        assert w._title == "Transform"

    def test_collapsed_defaults_to_false(self):
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        assert w._collapsed is False

    def test_collapsed_param_stored(self):
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo", collapsed=True)
        assert w._collapsed is True

    def test_empty_title_allowed(self):
        """``title=""`` is the opt-out sentinel used by
        :class:`AttributesWidget` — must not raise."""
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="")
        assert w._title == ""

    def test_initial_ui_handles_are_none(self):
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        assert w._frame is None
        assert w._content is None

    def test_initial_filter_subscription_is_none(self):
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        assert w._filter_model is None
        assert w._filter_sub_id is None

    def test_initial_pending_rebuild_is_none(self):
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        assert w._pending_rebuild_handle is None


# ---------------------------------------------------------------------------
# on_new_payload default
# ---------------------------------------------------------------------------


class TestOnNewPayloadDefault:
    def test_default_returns_true_for_any_payload(self):
        from ovwidgets.property.payload import PropertyPayload
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        assert w.on_new_payload(PropertyPayload(paths=["/World/A"])) is True

    def test_default_returns_true_for_empty_payload(self):
        from ovwidgets.property.payload import PropertyPayload
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        assert w.on_new_payload(PropertyPayload(paths=[])) is True

    def test_subclass_can_return_false(self):
        """Docstring promises subclasses may return False to hide."""
        from ovwidgets.property.widget import SimplePropertyWidget

        class _Hides(SimplePropertyWidget):
            def on_new_payload(self, payload):  # type: ignore[override]
                return False

        assert _Hides(title="x").on_new_payload(object()) is False


# ---------------------------------------------------------------------------
# build_items — CollapsableFrame scaffolding
# ---------------------------------------------------------------------------


class TestBuildItemsCreatesFrame:
    def test_creates_collapsable_frame_with_title(self, fake_ui):
        """Required by the Step 6.3 done-signal: CollapsableFrame created
        with correct title."""
        frame_cls, _ = fake_ui
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Transform")
        w.build_items()
        assert len(frame_cls.instances) == 1
        assert frame_cls.instances[0].kwargs["title"] == "Transform"

    def test_collapsable_frame_receives_initial_collapsed_state(self, fake_ui):
        frame_cls, _ = fake_ui
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Transform", collapsed=True)
        w.build_items()
        assert frame_cls.instances[0].kwargs["collapsed"] is True

    def test_collapsable_frame_styled_as_property_group_frame(self, fake_ui):
        frame_cls, _ = fake_ui
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Transform")
        w.build_items()
        assert (
            frame_cls.instances[0].kwargs["style_type_name_override"]
            == "Property.GroupFrame"
        )

    def test_collapsable_frame_uses_compact_property_header_builder(self, fake_ui):
        frame_cls, _ = fake_ui
        from ovwidgets.property.group_widget import build_property_group_header
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Transform")
        w.build_items()
        assert frame_cls.instances[0].kwargs["build_header_fn"] is build_property_group_header

    def test_collapsable_frame_uses_fit_content_height(self, fake_ui):
        frame_cls, _ = fake_ui
        from ovwidgets.property.group_widget import FIT_CONTENT_HEIGHT
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Transform")
        w.build_items()
        assert frame_cls.instances[0].kwargs["height"] == FIT_CONTENT_HEIGHT

    def test_vstack_created_inside_frame(self, fake_ui):
        frame_cls, vstack_cls = fake_ui
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Transform")
        w.build_items()
        assert len(frame_cls.instances) == 1
        assert len(vstack_cls.instances) == 1
        assert w._frame is frame_cls.instances[0]
        assert w._content is vstack_cls.instances[0]

    def test_content_stack_uses_fit_content_height(self, fake_ui):
        _, vstack_cls = fake_ui
        from ovwidgets.property.group_widget import FIT_CONTENT_HEIGHT
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Transform")
        w.build_items()
        assert vstack_cls.instances[0].kwargs["height"] == FIT_CONTENT_HEIGHT

    def test_content_stack_has_no_internal_vertical_gap(self, fake_ui):
        _, vstack_cls = fake_ui
        from ovwidgets.property.group_widget import GROUP_CONTENT_SPACING
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Transform")
        w.build_items()
        assert vstack_cls.instances[0].kwargs["spacing"] == GROUP_CONTENT_SPACING
        assert GROUP_CONTENT_SPACING == 5

    def test_empty_title_skips_frame(self, fake_ui):
        """``title=""`` is the opt-out sentinel — no frame created."""
        frame_cls, vstack_cls = fake_ui
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="")
        w.build_items()
        assert frame_cls.instances == []
        assert vstack_cls.instances == []
        assert w._frame is None
        assert w._content is None


# ---------------------------------------------------------------------------
# build_items_content — subclass hook
# ---------------------------------------------------------------------------


class TestBuildItemsContentHook:
    def test_default_is_no_op(self, fake_ui):
        """Default hook does nothing — subclasses opt in."""
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        w.build_items_content()  # must not raise

    def test_hook_invoked_inside_frame(self, fake_ui):
        from ovwidgets.property.widget import SimplePropertyWidget

        calls: List[Any] = []

        class _Sub(SimplePropertyWidget):
            def build_items_content(self):  # type: ignore[override]
                # When build_items runs, ``self._content`` is live
                # because SimplePropertyWidget opened the VStack.
                calls.append(self._content)

        sub = _Sub(title="Foo")
        sub.build_items()
        assert len(calls) == 1
        assert calls[0] is sub._content
        assert sub._content is not None

    def test_hook_invoked_without_frame_when_title_empty(self, fake_ui):
        from ovwidgets.property.widget import SimplePropertyWidget

        calls: List[Any] = []

        class _Sub(SimplePropertyWidget):
            def build_items_content(self):  # type: ignore[override]
                calls.append(self._content)

        sub = _Sub(title="")
        sub.build_items()
        assert len(calls) == 1
        # ``title=""`` path sets ``_content`` to None.
        assert calls[0] is None

    def test_subclass_can_override_build_items(self, fake_ui):
        """Docstring promises subclasses may override build_items directly.

        :class:`AttributesWidget` takes this path in its Step 6.3 shape —
        pinned by the AttributesWidget sibling test module, but the
        override-point itself is verified here."""
        from ovwidgets.property.widget import SimplePropertyWidget

        calls: List[str] = []

        class _Sub(SimplePropertyWidget):
            def build_items(self):  # type: ignore[override]
                calls.append("built")

        _Sub(title="Foo").build_items()
        assert calls == ["built"]


# ---------------------------------------------------------------------------
# add_item / add_item_with_model
# ---------------------------------------------------------------------------


class TestAddItem:
    def test_add_item_invokes_builder_inside_content(self, fake_ui):
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        w.build_items()  # populates ``_content``
        assert w._content is not None
        enters_before = w._content.enter_count

        calls: List[int] = []

        def _builder() -> None:
            calls.append(1)

        w.add_item(_builder)
        assert calls == [1]
        assert w._content.enter_count == enters_before + 1
        assert w._content.exit_count == enters_before + 1

    def test_add_item_runs_in_ambient_scope_when_no_content(self, fake_ui):
        """Pre-build_items (no content yet) — builder still invoked but
        outside any ``with`` scope."""
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        calls: List[int] = []
        w.add_item(lambda: calls.append(1))
        assert calls == [1]

    def test_add_item_with_model_forwards_model(self, fake_ui):
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        w.build_items()
        captured: List[Any] = []
        sentinel = object()

        def _builder(model: Any) -> None:
            captured.append(model)

        w.add_item_with_model(sentinel, _builder)
        assert captured == [sentinel]

    def test_add_item_with_model_runs_in_ambient_scope_when_no_content(self, fake_ui):
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        captured: List[Any] = []
        w.add_item_with_model("m", lambda m: captured.append(m))
        assert captured == ["m"]


# ---------------------------------------------------------------------------
# request_rebuild
# ---------------------------------------------------------------------------


class TestRequestRebuild:
    def test_request_rebuild_schedules_via_application(self, fake_app):
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        w.request_rebuild()
        assert len(fake_app.scheduled) == 1
        assert fake_app.scheduled[0].delay == 0.0  # type: ignore[attr-defined]

    def test_request_rebuild_coalesces_pending(self, fake_app):
        """Second call cancels the first — one live handle at a time."""
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        w.request_rebuild()
        first = fake_app.scheduled[0]
        w.request_rebuild()
        assert first.cancelled is True
        assert len(fake_app.scheduled) == 2
        assert fake_app.scheduled[1].cancelled is False

    def test_request_rebuild_no_app_is_noop(self, monkeypatch):
        """Application.instance() raises when no app — widget must not crash."""
        from ovwidgets.app.application import Application
        from ovwidgets.property.widget import SimplePropertyWidget
        monkeypatch.setattr(Application, "_instance", None)
        w = SimplePropertyWidget(title="Foo")
        w.request_rebuild()  # must not raise
        assert w._pending_rebuild_handle is None

    def test_do_rebuild_calls_frame_rebuild(self, fake_ui):
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        w.build_items()
        assert w._frame is not None
        w._do_rebuild()
        assert w._frame.rebuild_calls == 1

    def test_do_rebuild_no_op_without_frame(self, fake_ui):
        """``title=""`` → no frame — ``_do_rebuild`` just clears the handle."""
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="")
        w.build_items()
        assert w._frame is None
        w._do_rebuild()  # must not raise


# ---------------------------------------------------------------------------
# Filter subscription
# ---------------------------------------------------------------------------


class TestSubscribeFilter:
    def test_subscribe_filter_registers_callback(self):
        from ovwidgets.property.widget import SimplePropertyWidget
        model = _FakeModel()
        w = SimplePropertyWidget(title="Foo")
        w.subscribe_filter(model)
        assert model.live_subscriptions == 1

    def test_subscribe_filter_stores_model_and_id(self):
        from ovwidgets.property.widget import SimplePropertyWidget
        model = _FakeModel()
        w = SimplePropertyWidget(title="Foo")
        w.subscribe_filter(model)
        assert w._filter_model is model
        assert w._filter_sub_id is not None

    def test_filter_change_fires_request_rebuild(self, fake_app):
        """End-to-end: subscribing + firing the model fires request_rebuild."""
        from ovwidgets.property.widget import SimplePropertyWidget
        model = _FakeModel()
        w = SimplePropertyWidget(title="Foo")
        w.subscribe_filter(model)
        assert len(fake_app.scheduled) == 0
        model.fire()
        assert len(fake_app.scheduled) == 1

    def test_resubscribe_drops_prior(self):
        """Re-subscribing replaces the prior registration."""
        from ovwidgets.property.widget import SimplePropertyWidget
        m1 = _FakeModel()
        m2 = _FakeModel()
        w = SimplePropertyWidget(title="Foo")
        w.subscribe_filter(m1)
        first_id = w._filter_sub_id
        w.subscribe_filter(m2)
        assert m1.remove_calls == [first_id]
        assert m1.live_subscriptions == 0
        assert m2.live_subscriptions == 1
        assert w._filter_model is m2


# ---------------------------------------------------------------------------
# destroy — cleanup
# ---------------------------------------------------------------------------


class TestDestroy:
    def test_destroy_cancels_pending_rebuild(self, fake_app):
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        w.request_rebuild()
        handle = fake_app.scheduled[0]
        w.destroy()
        assert handle.cancelled is True
        assert w._pending_rebuild_handle is None

    def test_destroy_unsubscribes_filter(self):
        from ovwidgets.property.widget import SimplePropertyWidget
        model = _FakeModel()
        w = SimplePropertyWidget(title="Foo")
        w.subscribe_filter(model)
        sub_id = w._filter_sub_id
        w.destroy()
        assert model.remove_calls == [sub_id]
        assert model.live_subscriptions == 0
        assert w._filter_model is None
        assert w._filter_sub_id is None

    def test_destroy_drops_ui_handles(self, fake_ui):
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        w.build_items()
        assert w._frame is not None
        assert w._content is not None
        w.destroy()
        assert w._frame is None
        assert w._content is None

    def test_destroy_is_idempotent(self):
        """No subscription, no pending rebuild — destroy must not raise."""
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        w.destroy()
        w.destroy()  # must not raise

    def test_destroy_survives_never_built_widget(self):
        """Widget that was never :meth:`build_items`'d — destroy is safe."""
        from ovwidgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        w.destroy()  # must not raise


# ---------------------------------------------------------------------------
# AttributesWidget rebase (Step 6.3)
# ---------------------------------------------------------------------------


class TestAttributesWidgetRebase:
    def test_attributes_widget_is_simple_property_widget_subclass(self):
        """Step 6.3: AttributesWidget now inherits from SimplePropertyWidget."""
        from ovwidgets.property.widget import AttributesWidget, SimplePropertyWidget
        assert issubclass(AttributesWidget, SimplePropertyWidget)

    def test_attributes_widget_still_property_widget_subclass(self):
        """The Step 6.1 ABC contract is preserved through the rebase."""
        from ovwidgets.property.widget import AttributesWidget, PropertyWidget
        assert issubclass(AttributesWidget, PropertyWidget)

    def test_attributes_widget_passes_empty_title(self):
        """Visual parity: ``title=""`` skips the inherited frame wrapper."""
        from ovwidgets.property.widget import AttributesWidget
        aw = AttributesWidget.__new__(AttributesWidget)
        # Initialise the inherited state the way SimplePropertyWidget does
        # so we can read the title field without running the full __init__
        # (which would try to import the window module).
        from ovwidgets.property.widget.simple_property_widget import SimplePropertyWidget
        SimplePropertyWidget.__init__(aw, title="", collapsed=False)
        aw._window = None
        assert aw._title == ""

    def test_attributes_widget_build_items_skips_frame(self, fake_ui):
        """Because ``title=""`` the inherited :meth:`build_items` runs
        :meth:`build_items_content` in the ambient scope — no frame."""
        from ovwidgets.property.widget import AttributesWidget
        from ovwidgets.property.widget.simple_property_widget import SimplePropertyWidget
        aw = AttributesWidget.__new__(AttributesWidget)
        SimplePropertyWidget.__init__(aw, title="", collapsed=False)
        aw._window = None
        # Patch _build_groups so we exercise only the scaffolding layer.
        calls: List[int] = []
        aw._build_groups = lambda: calls.append(1)  # type: ignore[method-assign]
        aw.build_items()
        frame_cls, _ = fake_ui
        assert frame_cls.instances == []
        assert calls == [1]

    def test_attributes_widget_destroy_super_calls(self, fake_app):
        """AttributesWidget.destroy must call super().destroy() so the
        inherited pending-rebuild handle is cancelled."""
        from ovwidgets.property.widget import AttributesWidget
        from ovwidgets.property.widget.simple_property_widget import SimplePropertyWidget
        aw = AttributesWidget.__new__(AttributesWidget)
        SimplePropertyWidget.__init__(aw, title="", collapsed=False)
        aw._window = None
        aw.request_rebuild()
        handle = fake_app.scheduled[0]
        aw.destroy()
        assert handle.cancelled is True
