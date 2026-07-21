# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""CI invariant: ``PropertyWindow`` builds property adapters via injected factory.

Step 26 (Rev 4 §10.5 / pre-planning §6.3 property row) — corrected
after Codex Step 26 review
flagged the original static source-grep test as too brittle. The
behavioral test below uses a real ``Application`` instance with a
:class:`MagicMock` property window and an in-memory ``Usd.Stage`` to
exercise the full ``open_stage`` path — that catches a future regression
where the factory is wired in dead code, in the wrong function, or via
a refactored helper that preserves the source string but breaks the
behavior.

Three contract layers are pinned:

  1. A freshly-constructed ``PropertyWindow`` has no factory installed
     and ``_create_adapter_for_paths`` returns ``None``.
  2. ``set_property_adapter_factory`` stores the callable; subsequent
     ``_create_adapter_for_paths`` calls forward the paths to it.
  3. ``Application.open_stage(stage)`` actually calls
     ``set_property_adapter_factory(factory)`` once, the registered
     factory is callable and produces a ``UsdPropertyAdapter``, and the
     same flow wires ``set_stage_adapter(self._stage_adapter,
     self._undo_manager)`` with the live adapter + undo manager.
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock

import pytest

from ovui_widgets.property.window import PropertyWindow

# ---------------------------------------------------------------------------
# Behavioral fixtures — Application + in-memory USD stage
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_application_singleton():
    """Reset the Application/SelectionBus singletons around every test.

    Mirrors the pattern in ``test_application_renderer.py`` and
    ``test_renderer_unavailable_warning.py`` — ``Application.__init__``
    asserts that ``_instance is None`` so a stale singleton from a
    prior test would crash the next ``Application()`` call.
    """
    from ovui_widgets.app.application import Application
    from ovui_widgets.common.selection import SelectionBus

    Application._instance = None
    SelectionBus._instance = None
    try:
        yield
    finally:
        if Application._instance is not None:
            try:
                Application._instance.shutdown()
            except Exception:
                pass
            Application._instance = None
        SelectionBus._instance = None


# ---------------------------------------------------------------------------
# Layer 1 — fresh PropertyWindow has no factory
# ---------------------------------------------------------------------------


def test_fresh_property_window_has_no_factory():
    """Without a factory, the property window is a passive panel."""
    window = PropertyWindow()
    assert window._adapter_factory is None


def test_create_adapter_for_paths_without_factory_returns_none():
    """No factory → empty panel — the documented contract for
    selection changes that fire before ``Application`` installs the
    factory (e.g. cold startup with no stage).
    """
    window = PropertyWindow()
    assert window._create_adapter_for_paths(["/World/Cube"]) is None


# ---------------------------------------------------------------------------
# Layer 2 — set_property_adapter_factory + _create_adapter_for_paths plumbing
# ---------------------------------------------------------------------------


def test_set_property_adapter_factory_stores_the_callable():
    """``set_property_adapter_factory`` registers the factory verbatim."""
    window = PropertyWindow()
    sentinel = lambda paths: ("FAKE_ADAPTER", paths)
    window.set_property_adapter_factory(sentinel)
    assert window._adapter_factory is sentinel


def test_create_adapter_for_paths_uses_registered_factory():
    """``_create_adapter_for_paths`` forwards paths to the factory and
    returns its result.
    """
    window = PropertyWindow()
    received = []

    def factory(paths):
        received.append(list(paths))
        return ("FAKE_ADAPTER", list(paths))

    window.set_property_adapter_factory(factory)
    out = window._create_adapter_for_paths(["/World/Cube", "/World/Sphere"])
    assert out == ("FAKE_ADAPTER", ["/World/Cube", "/World/Sphere"])
    assert received == [["/World/Cube", "/World/Sphere"]]


def test_create_adapter_for_paths_swallows_factory_exception():
    """A factory that raises must not blow up the window — Step 10's
    documented behaviour returns the previous adapter (or ``None``)
    so the panel keeps its last good state.
    """
    window = PropertyWindow()
    window._adapter = None  # no prior adapter

    def broken_factory(paths):
        raise RuntimeError("synthetic")

    window.set_property_adapter_factory(broken_factory)
    out = window._create_adapter_for_paths(["/World/Cube"])
    assert out is None


# ---------------------------------------------------------------------------
# Layer 3 — Application.open_stage() behavioral wiring (Codex correction)
# ---------------------------------------------------------------------------


pytest.importorskip("pxr")


def _build_in_memory_stage():
    """Tiny stage with one Cube — enough for the property factory to
    resolve a real prim path on construction.
    """
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Cube.Define(stage, "/World/Cube")
    return stage


def test_application_open_stage_registers_property_adapter_factory():
    """``Application.open_stage()`` must call
    ``property_window.set_property_adapter_factory(factory)`` exactly
    once, the captured factory must be callable, and calling it must
    return a real ``UsdPropertyAdapter`` (not a string, not ``None``).

    Behavioral test — replaces the brittle source-grep that the Codex
    Step 26 review rejected. A future refactor that quietly swaps to a
    direct ``UsdPropertyAdapter(stage, …)`` constructor call (bypassing
    the factory injection) would fail this test even if the helper
    function name and source layout look unchanged.
    """
    from ovui_data_adapters.openusd import UsdPropertyAdapter

    from ovui_widgets.app.application import Application

    app = Application()
    property_window = MagicMock(name="PropertyWindow")
    app._property_window = property_window
    # Other windows stay None — open_stage's ``if self._foo is not None``
    # guards skip them safely.

    stage = _build_in_memory_stage()
    app.open_stage(stage)

    # Exactly one factory registration.
    property_window.set_property_adapter_factory.assert_called_once()
    factory = property_window.set_property_adapter_factory.call_args.args[0]
    assert callable(factory), "registered factory must be callable"

    # Calling the factory returns a UsdPropertyAdapter instance — proves
    # the closure captured the live ``stage`` / ``_stage_adapter`` /
    # ``_undo_manager`` and constructs the right concrete adapter.
    adapter = factory(["/World/Cube"])
    assert isinstance(adapter, UsdPropertyAdapter), (
        f"factory must produce UsdPropertyAdapter, got {type(adapter).__name__}"
    )


def test_application_open_stage_wires_set_stage_adapter():
    """Same flow must also call
    ``property_window.set_stage_adapter(self._stage_adapter,
    self._undo_manager)`` so the property window can subscribe to
    stage-change events for the freshly-loaded stage.
    """
    from ovui_widgets.app.application import Application

    app = Application()
    property_window = MagicMock(name="PropertyWindow")
    app._property_window = property_window

    stage = _build_in_memory_stage()
    app.open_stage(stage)

    property_window.set_stage_adapter.assert_called_once()
    args, kwargs = property_window.set_stage_adapter.call_args
    # The hand-off shape is positional: (stage_adapter, undo_manager).
    assert len(args) >= 2, f"expected (stage_adapter, undo_manager), got args={args!r} kwargs={kwargs!r}"
    stage_adapter, undo_manager = args[0], args[1]
    assert stage_adapter is app._stage_adapter, (
        "set_stage_adapter must receive the live ``app._stage_adapter`` "
        "(not a stale or freshly-constructed copy)"
    )
    assert undo_manager is app._undo_manager, (
        "set_stage_adapter must receive the live ``app._undo_manager``"
    )


def test_application_open_stage_factory_uses_openusd_adapter_path():
    """The factory must construct the openusd-side adapter, not a
    widget-side one — the data-adapters split forbids importing
    ``UsdPropertyAdapter`` from ``ovui_widgets.*``. Verifies the produced
    instance's class object is the same one exported by the openusd
    package, not a forked copy from elsewhere in ``sys.modules``.
    """
    from ovui_data_adapters.openusd import UsdPropertyAdapter as ExpectedClass

    from ovui_widgets.app.application import Application

    app = Application()
    property_window = MagicMock(name="PropertyWindow")
    app._property_window = property_window

    stage = _build_in_memory_stage()
    app.open_stage(stage)

    factory = property_window.set_property_adapter_factory.call_args.args[0]
    adapter = factory(["/World/Cube"])
    assert type(adapter) is ExpectedClass, (
        f"factory must return ovui_data_adapters.openusd.UsdPropertyAdapter; "
        f"got {type(adapter).__module__}.{type(adapter).__name__}"
    )
