# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 7.4 — large-selection gate.

the property inspector step 7.4 done signal: "150-path payload → only the
banner appears, no rows built. Clicking the button forces a build."

Architecture: :class:`~ovui_widgets.property.window.PropertyWindow._rebuild_content`
now builds a :class:`~ovui_widgets.property.payload.PropertyPayload` at the top
of every rebuild and gates on
:meth:`PropertyPayload.is_large_selection`. When the gate fires AND the
override flag is False, the window renders a "N items selected —
property display suppressed. Click to load anyway." banner with a
"Load Anyway" button in place of the full attribute build. Clicking
the button sets :attr:`PropertyWindow._large_selection_override` to
True and re-enters :meth:`_rebuild_content`, which now takes the
full-build branch. :meth:`PropertyWindow.set_selection` resets the
override flag whenever the selection actually changes, so the next
large-selection payload hits the gate again rather than silently
inheriting the prior override.

The tests run fully headless — no ``omni.ui`` root required. They
monkeypatch :func:`ui.Label`, :func:`ui.Button` and :func:`ui.VStack`
at the ``ovui_widgets.property.window.ui`` namespace so the banner build's
UI-construction calls are observable without instantiating real
widgets. :meth:`PropertyWindow._build_registered_widgets` is also
monkeypatched to record invocations so tests can assert which
branch of the gate fired.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional

import pytest

# ---------------------------------------------------------------------------
# Test doubles — recorders for the two gate branches
# ---------------------------------------------------------------------------


class _FakeVStack:
    """Plain ``VStack`` stand-in used as :attr:`PropertyWindow._content`.

    The rebuild drives ``_content.clear()`` and opens a
    ``with self._content:`` block. A no-op context manager + no-op
    ``clear()`` is enough to exercise the rebuild without a live ovui
    root. The banner build opens a nested ``ui.VStack`` which is
    substituted via the monkeypatched ``ui.VStack`` symbol below.
    """

    def __init__(self) -> None:
        self.clear_calls: int = 0

    def clear(self) -> None:
        self.clear_calls += 1

    def __enter__(self) -> "_FakeVStack":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


class _FakeInnerVStack:
    """Stand-in for the inner ``ui.VStack`` the banner opens.

    Construction records the kwargs so tests can assert the expected
    style override / spacing land on the banner container. ``__enter__``
    / ``__exit__`` short-circuit to support the banner's
    ``with ui.VStack(...)`` block.
    """

    calls: List["_FakeInnerVStack"] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        _FakeInnerVStack.calls.append(self)

    def __enter__(self) -> "_FakeInnerVStack":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


class _FakeLabel:
    """Recording stand-in for :class:`ui.Label` under the banner build."""

    calls: List["_FakeLabel"] = []

    def __init__(self, text: str, **kwargs: Any) -> None:
        self.text = text
        self.kwargs = kwargs
        self.mouse_pressed_fn: Optional[Callable[..., None]] = None
        _FakeLabel.calls.append(self)

    def set_mouse_pressed_fn(self, fn: Callable[..., None]) -> None:
        self.mouse_pressed_fn = fn


class _FakeButton:
    """Recording stand-in for :class:`ui.Button` under the banner build.

    Exposes the registered ``clicked_fn`` so tests can fire the click
    without a real ovui root.
    """

    calls: List["_FakeButton"] = []

    def __init__(self, text: str, **kwargs: Any) -> None:
        self.text = text
        self.kwargs = kwargs
        self.clicked_fn: Optional[Callable[[], None]] = kwargs.get("clicked_fn")
        _FakeButton.calls.append(self)


@pytest.fixture(autouse=True)
def _reset_fake_recorders():
    """Reset the class-level recorders between tests."""
    _FakeInnerVStack.calls = []
    _FakeLabel.calls = []
    _FakeButton.calls = []
    yield
    _FakeInnerVStack.calls = []
    _FakeLabel.calls = []
    _FakeButton.calls = []


class _FakeSpacer:
    """Recording stand-in for :class:`ui.Spacer` under the banner build."""

    calls: List["_FakeSpacer"] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        _FakeSpacer.calls.append(self)


@pytest.fixture()
def patched_ui(monkeypatch):
    """Patch ``ui.VStack`` / ``ui.Label`` / ``ui.Button`` / ``ui.Spacer``
    on the window module.

    The banner build reaches the ovui namespace via the module-level
    ``import omni.ui as ui`` in :mod:`ovui_widgets.property.window`. Patching
    ``window.ui.VStack`` and friends catches every construction in the
    banner path without needing an ovui root.

    ``ui.Percent`` is used for the button width — patch it to an
    identity function so the banner build does not crash.
    """
    import ovui_widgets.property.window as window_mod

    _FakeSpacer.calls = []
    monkeypatch.setattr(window_mod.ui, "VStack", _FakeInnerVStack)
    monkeypatch.setattr(window_mod.ui, "Label", _FakeLabel)
    monkeypatch.setattr(window_mod.ui, "Button", _FakeButton)
    monkeypatch.setattr(window_mod.ui, "Spacer", _FakeSpacer)
    monkeypatch.setattr(window_mod.ui, "Percent", lambda v: v)
    return window_mod


# ---------------------------------------------------------------------------
# Headless PropertyWindow factory
# ---------------------------------------------------------------------------


def _make_headless_window():
    """Build a :class:`PropertyWindow` without invoking ``__init__``.

    Mirrors the pattern used in every other Phase 6 / Phase 7 test
    file. Seeds only the fields :meth:`_rebuild_content` reads so the
    rebuild exercise is self-contained. The class-level
    :attr:`_large_selection_threshold` / :attr:`_large_selection_override`
    defaults cover the Step 7.4 surface without per-instance seeds.
    """
    from ovui_widgets.property.window import PropertyWindow

    w = PropertyWindow.__new__(PropertyWindow)
    w._adapter = object()  # truthy non-None — rebuild predicate only tests bool
    w._selection = []
    w._filter_text = ""
    w._pending_filter_handle = None
    w._filter_field = None
    w._content = _FakeVStack()
    w._group_collapse_state = {}
    w._active_context_menu = None
    w._bus_sub = None
    w._stage_adapter = None
    w._stage_change_sub = None
    w._undo_manager_ref = None
    w._widgets = []
    w._default_attributes = None
    w._scroll_frame = None
    w._scroll_preserver = None
    return w


def _make_paths(count: int) -> List[str]:
    """Generate ``count`` unique-looking USD path strings."""
    return [f"/World/Prim{i:04d}" for i in range(count)]


def _banner_stacks() -> List[_FakeInnerVStack]:
    """Return only large-selection banner containers, excluding filter chrome."""
    return [
        stack for stack in _FakeInnerVStack.calls
        if stack.kwargs.get("style_type_name_override")
        == "Property.LargeSelectionBanner"
    ]


def _banner_labels() -> List[_FakeLabel]:
    """Return only large-selection banner labels, excluding filter placeholders."""
    return [
        label for label in _FakeLabel.calls
        if "property display suppressed" in label.text.lower()
    ]


# ---------------------------------------------------------------------------
# Gate branch — 150 paths triggers the banner, _build_registered_widgets
# is NOT called
# ---------------------------------------------------------------------------


class TestGateFiresForLargeSelection:
    def test_150_paths_builds_banner(self, patched_ui, monkeypatch):
        """150-path payload → banner appears, no attribute rows built."""
        w = _make_headless_window()
        w._selection = _make_paths(150)

        build_calls: List[int] = []
        monkeypatch.setattr(
            w, "_build_registered_widgets",
            lambda: build_calls.append(1),
        )

        w._rebuild_content()

        # Banner opened exactly one banner VStack + one banner Label + one Button.
        assert len(_banner_stacks()) == 1
        assert len(_banner_labels()) == 1
        assert len(_FakeButton.calls) == 1
        # Attribute build path did NOT fire.
        assert build_calls == []

    def test_banner_message_includes_count(self, patched_ui, monkeypatch):
        """Label text quotes the exact selection count."""
        w = _make_headless_window()
        w._selection = _make_paths(150)
        monkeypatch.setattr(w, "_build_registered_widgets", lambda: None)

        w._rebuild_content()

        labels = _banner_labels()
        assert labels, "Banner label was not constructed"
        label = labels[0]
        assert "150" in label.text
        assert "property display suppressed" in label.text.lower()
        assert "load anyway" in label.text.lower()

    def test_banner_button_labeled_load_anyway(self, patched_ui, monkeypatch):
        """The button advertises the override action with "Load Anyway"."""
        w = _make_headless_window()
        w._selection = _make_paths(150)
        monkeypatch.setattr(w, "_build_registered_widgets", lambda: None)

        w._rebuild_content()

        assert _FakeButton.calls, "Banner button was not constructed"
        btn = _FakeButton.calls[0]
        assert btn.text == "Load Anyway"

    def test_banner_button_has_clicked_handler(self, patched_ui, monkeypatch):
        """The button is wired to a handler — a banner with no handler
        would leave the user with no way to bypass the gate."""
        w = _make_headless_window()
        w._selection = _make_paths(150)
        monkeypatch.setattr(w, "_build_registered_widgets", lambda: None)

        w._rebuild_content()

        btn = _FakeButton.calls[0]
        assert btn.clicked_fn is not None
        assert callable(btn.clicked_fn)


# ---------------------------------------------------------------------------
# Below-threshold — normal build path still runs
# ---------------------------------------------------------------------------


class TestBelowThresholdBuildsRows:
    def test_50_paths_takes_full_build_branch(self, patched_ui, monkeypatch):
        """50-path payload is below the default 100-path threshold —
        the normal attribute-build path runs and the banner helpers are
        not invoked."""
        w = _make_headless_window()
        w._selection = _make_paths(50)

        build_calls: List[int] = []
        monkeypatch.setattr(
            w, "_build_registered_widgets",
            lambda: build_calls.append(1),
        )

        w._rebuild_content()

        assert build_calls == [1]
        assert _banner_labels() == []
        assert _FakeButton.calls == []

    def test_99_paths_still_below_threshold(self, patched_ui, monkeypatch):
        """99 paths → still below the inclusive default threshold of 100."""
        w = _make_headless_window()
        w._selection = _make_paths(99)

        build_calls: List[int] = []
        monkeypatch.setattr(
            w, "_build_registered_widgets",
            lambda: build_calls.append(1),
        )

        w._rebuild_content()

        assert build_calls == [1]
        assert _banner_labels() == []

    def test_100_paths_hits_gate_inclusive(self, patched_ui, monkeypatch):
        """``is_large_selection`` uses ``>=`` — 100 paths exactly should
        trigger the banner. Mirrors the boundary semantic pinned by
        ``test_property_payload.py::TestLargeSelection``."""
        w = _make_headless_window()
        w._selection = _make_paths(100)

        build_calls: List[int] = []
        monkeypatch.setattr(
            w, "_build_registered_widgets",
            lambda: build_calls.append(1),
        )

        w._rebuild_content()

        assert build_calls == []
        labels = _banner_labels()
        assert len(labels) == 1
        assert "100" in labels[0].text


# ---------------------------------------------------------------------------
# Override — clicking "Load Anyway" forces a full build
# ---------------------------------------------------------------------------


class TestOverrideForcesFullBuild:
    def test_button_click_flips_override_flag(self, patched_ui, monkeypatch):
        """Clicking the button sets :attr:`_large_selection_override`."""
        w = _make_headless_window()
        w._selection = _make_paths(150)
        monkeypatch.setattr(w, "_build_registered_widgets", lambda: None)

        w._rebuild_content()
        assert w._large_selection_override is False

        btn = _FakeButton.calls[0]
        btn.clicked_fn()  # simulate click

        assert w._large_selection_override is True

    def test_button_click_triggers_rebuild(self, patched_ui, monkeypatch):
        """Clicking the button re-enters :meth:`_rebuild_content` so
        the full attribute build runs in place of the banner."""
        w = _make_headless_window()
        w._selection = _make_paths(150)

        build_calls: List[int] = []
        monkeypatch.setattr(
            w, "_build_registered_widgets",
            lambda: build_calls.append(1),
        )

        w._rebuild_content()
        # Pre-click: banner rendered, no attribute build.
        assert build_calls == []
        assert len(_FakeButton.calls) == 1

        btn = _FakeButton.calls[0]
        btn.clicked_fn()

        # Post-click: banner no longer rendered, attribute build ran.
        assert build_calls == [1]

    def test_override_skips_gate_on_subsequent_rebuild(
        self, patched_ui, monkeypatch
    ):
        """Once the override is True, further rebuilds of the same
        payload take the full-build branch. The banner does not come
        back unless the override is reset."""
        w = _make_headless_window()
        w._selection = _make_paths(200)
        w._large_selection_override = True

        build_calls: List[int] = []
        monkeypatch.setattr(
            w, "_build_registered_widgets",
            lambda: build_calls.append(1),
        )

        w._rebuild_content()
        assert build_calls == [1]
        assert _banner_labels() == []

    def test_override_handler_is_idempotent(self, patched_ui, monkeypatch):
        """Calling the handler a second time (through a latent banner
        reference) does not regress: flag stays True, rebuild runs
        again but stays on the full-build branch."""
        w = _make_headless_window()
        w._selection = _make_paths(150)

        build_calls: List[int] = []
        monkeypatch.setattr(
            w, "_build_registered_widgets",
            lambda: build_calls.append(1),
        )

        w._rebuild_content()
        btn = _FakeButton.calls[0]
        btn.clicked_fn()
        assert build_calls == [1]

        btn.clicked_fn()  # second click — still idempotent
        assert w._large_selection_override is True
        assert build_calls == [1, 1]


# ---------------------------------------------------------------------------
# Override reset — new selection drops the flag
# ---------------------------------------------------------------------------


class TestOverrideResetsOnNewPayload:
    def test_set_selection_resets_override(self, patched_ui, monkeypatch):
        """A selection change resets :attr:`_large_selection_override`
        so the next large-selection payload hits the gate again."""
        w = _make_headless_window()
        w._selection = _make_paths(150)
        w._large_selection_override = True

        build_calls: List[int] = []
        monkeypatch.setattr(
            w, "_build_registered_widgets",
            lambda: build_calls.append(1),
        )

        # New selection — distinct list, still large.
        new_paths = _make_paths(200)
        w.set_selection(new_paths)

        assert w._large_selection_override is False
        # The rebuild that set_selection triggered ran with the override
        # cleared → banner path fired, full build did NOT run.
        assert build_calls == []
        assert len(_banner_labels()) == 1

    def test_same_selection_does_not_reset_override(
        self, patched_ui, monkeypatch
    ):
        """An identical-selection re-publish early-returns before
        touching the override flag — a user-triggered "re-select the
        same thing" doesn't silently re-gate a payload they already
        overrode."""
        w = _make_headless_window()
        w._selection = _make_paths(150)
        w._large_selection_override = True

        build_calls: List[int] = []
        monkeypatch.setattr(
            w, "_build_registered_widgets",
            lambda: build_calls.append(1),
        )

        same_paths = _make_paths(150)  # equal list
        w.set_selection(same_paths)

        assert w._large_selection_override is True
        # No rebuild fired (equality short-circuit in set_selection).
        assert build_calls == []
        assert _FakeLabel.calls == []

    def test_new_small_selection_resets_override(
        self, patched_ui, monkeypatch
    ):
        """Even when the NEW selection is small, the override still
        resets — so a subsequent large selection gets re-gated."""
        w = _make_headless_window()
        w._selection = _make_paths(150)
        w._large_selection_override = True

        build_calls: List[int] = []
        monkeypatch.setattr(
            w, "_build_registered_widgets",
            lambda: build_calls.append(1),
        )

        small = _make_paths(5)
        w.set_selection(small)

        assert w._large_selection_override is False
        assert build_calls == [1]  # small build ran

    def test_override_gate_recurrence_across_selections(
        self, patched_ui, monkeypatch
    ):
        """End-to-end: large sel → override → small sel → another
        large sel re-gates. Proves the override is a per-payload flag,
        not a sticky preference."""
        w = _make_headless_window()
        w._selection = []

        build_calls: List[int] = []
        monkeypatch.setattr(
            w, "_build_registered_widgets",
            lambda: build_calls.append(1),
        )

        # Selection 1 — large, gate fires
        w.set_selection(_make_paths(150))
        assert build_calls == []
        assert len(_FakeButton.calls) == 1

        # Override
        _FakeButton.calls[0].clicked_fn()
        assert build_calls == [1]
        assert w._large_selection_override is True

        # Selection 2 — small, override resets, small build runs
        w.set_selection(_make_paths(5))
        assert w._large_selection_override is False
        assert build_calls == [1, 1]

        # Selection 3 — large again, gate fires again (pre-reset state
        # now expired).
        w.set_selection(_make_paths(200))
        assert build_calls == [1, 1]
        assert len(_FakeButton.calls) == 2


# ---------------------------------------------------------------------------
# Threshold default + per-instance override
# ---------------------------------------------------------------------------


class TestThresholdKnob:
    def test_class_default_threshold_is_100(self):
        """Class-level default mirrors :meth:`PropertyPayload.is_large_selection`."""
        from ovui_widgets.property.window import PropertyWindow

        assert PropertyWindow._large_selection_threshold == 100

    def test_class_default_override_is_false(self):
        """Bypass-__init__ instances inherit the class-level default."""
        from ovui_widgets.property.window import PropertyWindow

        assert PropertyWindow._large_selection_override is False

    def test_instance_can_raise_threshold(self, patched_ui, monkeypatch):
        """A per-instance write on ``_large_selection_threshold`` should
        raise the gate — 150 paths with threshold=500 stays below."""
        w = _make_headless_window()
        w._selection = _make_paths(150)
        w._large_selection_threshold = 500

        build_calls: List[int] = []
        monkeypatch.setattr(
            w, "_build_registered_widgets",
            lambda: build_calls.append(1),
        )

        w._rebuild_content()

        assert build_calls == [1]
        assert _banner_labels() == []

    def test_instance_can_lower_threshold(self, patched_ui, monkeypatch):
        """Per-instance threshold of 10 fires the gate for 50 paths
        that are normally below the 100 default."""
        w = _make_headless_window()
        w._selection = _make_paths(50)
        w._large_selection_threshold = 10

        build_calls: List[int] = []
        monkeypatch.setattr(
            w, "_build_registered_widgets",
            lambda: build_calls.append(1),
        )

        w._rebuild_content()

        assert build_calls == []
        labels = _banner_labels()
        assert len(labels) == 1
        assert "50" in labels[0].text


# ---------------------------------------------------------------------------
# Empty + no-adapter — still early-return, gate never runs
# ---------------------------------------------------------------------------


class TestEmptyAndNoAdapterShortCircuit:
    def test_empty_selection_early_returns(self, patched_ui, monkeypatch):
        """Empty selection early-returns BEFORE the gate evaluates, so
        the large-selection banner never runs. QA BUG-002: a single
        "No selection" placeholder label is rendered instead."""
        w = _make_headless_window()
        w._selection = []

        build_calls: List[int] = []
        monkeypatch.setattr(
            w, "_build_registered_widgets",
            lambda: build_calls.append(1),
        )

        w._rebuild_content()

        assert build_calls == []
        # Exactly one Label — the QA BUG-002 "No selection" placeholder.
        assert len(_FakeLabel.calls) == 1
        assert _FakeLabel.calls[0].text == "No selection"

    def test_no_adapter_early_returns(self, patched_ui, monkeypatch):
        """``_adapter is None`` early-returns before the gate runs.

        QA BUG-002: the empty-selection placeholder label fires for the
        no-adapter case too (same early-return branch)."""
        w = _make_headless_window()
        w._adapter = None
        w._selection = _make_paths(150)  # large, but no adapter

        build_calls: List[int] = []
        monkeypatch.setattr(
            w, "_build_registered_widgets",
            lambda: build_calls.append(1),
        )

        w._rebuild_content()

        assert build_calls == []
        assert len(_FakeLabel.calls) == 1
        assert _FakeLabel.calls[0].text == "No selection"

    def test_no_content_early_returns(self, patched_ui, monkeypatch):
        """``_content is None`` early-returns before the gate runs."""
        w = _make_headless_window()
        w._content = None
        w._selection = _make_paths(150)

        build_calls: List[int] = []
        monkeypatch.setattr(
            w, "_build_registered_widgets",
            lambda: build_calls.append(1),
        )

        w._rebuild_content()

        assert build_calls == []
        assert _FakeLabel.calls == []


# ---------------------------------------------------------------------------
# Integration — banner text respects the payload count on re-rebuild
# ---------------------------------------------------------------------------


class TestRebuildUpdatesBannerText:
    def test_count_updates_when_selection_changes(
        self, patched_ui, monkeypatch
    ):
        """Two successive large selections produce banner text quoting
        each selection's own count."""
        w = _make_headless_window()
        w._selection = []
        monkeypatch.setattr(w, "_build_registered_widgets", lambda: None)

        w.set_selection(_make_paths(150))
        labels = _banner_labels()
        assert len(labels) == 1
        assert "150" in labels[0].text

        # New large selection, distinct count.
        w.set_selection(_make_paths(250))
        labels = _banner_labels()
        assert len(labels) == 2
        assert "250" in labels[1].text


# ---------------------------------------------------------------------------
# Handler surface — public contract of the new methods
# ---------------------------------------------------------------------------


class TestHandlerSurface:
    def test_on_ignore_threshold_clicked_exists(self):
        from ovui_widgets.property.window import PropertyWindow

        assert callable(PropertyWindow._on_ignore_threshold_clicked)

    def test_build_large_selection_banner_exists(self):
        from ovui_widgets.property.window import PropertyWindow

        assert callable(PropertyWindow._build_large_selection_banner)

    def test_banner_style_present_in_property_styles(self):
        """Step 7.4 ships a new ``Property.LargeSelectionBanner`` style
        selector so the banner is visually distinct from the regular
        attribute rows."""
        from ovui_widgets.property.style import PROPERTY_STYLES

        assert "Property.LargeSelectionBanner" in PROPERTY_STYLES
