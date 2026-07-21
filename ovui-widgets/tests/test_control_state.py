# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ControlStateManager and ControlStateIndicator — Step 4.3.

Covers the done-signal matrix from the property inspector 4.3:

* Priority ordering — Mixed (priority 0) wins over NotDefault (priority 40)
  when both predicates fire.
* Custom handler registration + cancel.
* No-handler case — ``get_active_state`` returns ``None`` and the
  indicator's image is hidden when no predicate matches.
* ``PropertyAdapter.clear_value`` exists on the ABC; mock raises
  ``NotImplementedError``; explicit ``clear_values`` capability support is
  required by the NotDefault predicate.

Plus a handful of edge anchors: Locked > TimeSampled > NotDefault
priority ordering; duplicate registration raises; cancel removes; the
NotDefault click handler swallows ``NotImplementedError`` so a runtime
adapter-capability swap cannot crash the panel; buggy third-party
predicates don't break neighbouring state resolution.

Tests do NOT instantiate :class:`ControlStateIndicator` — that requires
an omni.ui context. The indicator's behaviour is exercised indirectly
via the manager's ``get_active_state`` surface, which is the only
contract rows rely on.
"""

from __future__ import annotations

from typing import Any, List

import pytest
from ovui_data_adapters.common import (
    AdapterCapability,
    AttributeMetadata,
    PropertyAdapter,
    PropertyCapabilities,
)

from ovui_widgets.common.testing.mock_property import MockPropertyAdapter
from ovui_widgets.property.models import AttributeModelBase
from ovui_widgets.property.parts import ControlStateHandler, ControlStateManager
from ovui_widgets.property.parts.control_state import (
    _locked_predicate,
    _mixed_predicate,
    _not_default_on_click,
    _not_default_predicate,
    _time_sampled_predicate,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_manager():
    """Reset the ``ControlStateManager`` singleton before and after.

    The four built-in handlers are re-registered on the next
    ``get_instance()`` call; tests relying on a clean slate don't get
    polluted by handlers another test registered.
    """
    ControlStateManager._reset_for_tests()
    try:
        yield ControlStateManager.get_instance()
    finally:
        ControlStateManager._reset_for_tests()


def _make_metadata(
    *,
    is_ambiguous: bool = False,
    is_locked: bool = False,
    is_time_sampled: bool = False,
    is_authored: bool = True,
) -> AttributeMetadata:
    """Factory for a simple metadata object.

    ``is_ambiguous`` is stashed via a seeded per-path value on the
    mock adapter — see ``_build_model``. The metadata dataclass itself
    has no ``is_ambiguous`` field because ambiguity is a property of
    the selection, not the schema.
    """
    return AttributeMetadata(
        name="radius",
        display_name="Radius",
        type_name="float",
        value_type=float,
        group="Shape",
        is_locked=is_locked,
        is_time_sampled=is_time_sampled,
        is_authored=is_authored,
    )


class _ControlStatePropertyAdapter(MockPropertyAdapter):
    """Mock adapter with instance-configurable property capabilities."""

    def __init__(
        self,
        *args: Any,
        clear_values_supported: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._clear_values_supported = clear_values_supported

    def get_capabilities(self) -> PropertyCapabilities:
        return PropertyCapabilities(
            clear_values=(
                AdapterCapability.supported()
                if self._clear_values_supported
                else AdapterCapability.unsupported("clear disabled by test adapter")
            )
        )

    def clear_value(self, attr_name: str) -> None:
        self._values.pop(attr_name, None)


def _build_model(
    *,
    is_ambiguous: bool = False,
    is_locked: bool = False,
    is_time_sampled: bool = False,
    is_authored: bool = True,
    clear_values_supported: bool = False,
) -> AttributeModelBase:
    """Build an ``AttributeModelBase`` over a MockPropertyAdapter.

    ``is_ambiguous`` drives a two-path selection with disagreeing values
    so ``adapter.is_ambiguous`` reports True. ``clear_values_supported``
    toggles the explicit property capability consumed by the NotDefault
    predicate.
    """
    metadata = _make_metadata(
        is_locked=is_locked,
        is_time_sampled=is_time_sampled,
        is_authored=is_authored,
    )
    paths = ["/World/A", "/World/B"] if is_ambiguous else ["/World/A"]
    adapter = _ControlStatePropertyAdapter(
        paths=paths,
        attributes={"radius": metadata},
        clear_values_supported=clear_values_supported,
    )
    if is_ambiguous:
        adapter.set_path_value("/World/A", "radius", 1.0)
        adapter.set_path_value("/World/B", "radius", 2.0)
    else:
        adapter._values["radius"] = 1.0
    return AttributeModelBase(adapter, "radius", metadata)


# ---------------------------------------------------------------------------
# Done-signal #1: clear_value ABC surface
# ---------------------------------------------------------------------------


class TestClearValueOnAdapter:
    """``PropertyAdapter.clear_value`` exists and has the correct shape."""

    def test_clear_value_is_defined_on_abc(self) -> None:
        assert hasattr(PropertyAdapter, "clear_value")
        assert callable(PropertyAdapter.clear_value)

    def test_mock_adapter_raises_not_implemented(self) -> None:
        adapter = MockPropertyAdapter(
            paths=["/World/A"],
            attributes={"radius": _make_metadata()},
        )
        with pytest.raises(NotImplementedError):
            adapter.clear_value("radius")

    def test_clear_values_capability_distinguishes_reset_support(self) -> None:
        """NotDefault support comes from declared capability state."""
        unsupported = _build_model(is_authored=True, clear_values_supported=False)
        supported = _build_model(is_authored=True, clear_values_supported=True)
        assert type(unsupported.adapter) is type(supported.adapter)
        assert _not_default_predicate(unsupported) is False
        assert _not_default_predicate(supported) is True


# ---------------------------------------------------------------------------
# Done-signal #2: priority ordering
# ---------------------------------------------------------------------------


class TestPriorityOrdering:
    """Lower priority number wins when multiple predicates fire."""

    def test_mixed_wins_over_not_default_when_both_fire(
        self, fresh_manager: ControlStateManager
    ) -> None:
        model = _build_model(
            is_ambiguous=True,
            is_authored=True,
            clear_values_supported=True,
        )
        state = fresh_manager.get_active_state(model)
        assert state is not None
        assert state.name == "Mixed"

    def test_locked_wins_over_time_sampled_and_not_default(
        self, fresh_manager: ControlStateManager
    ) -> None:
        model = _build_model(
            is_locked=True,
            is_time_sampled=True,
            is_authored=True,
            clear_values_supported=True,
        )
        state = fresh_manager.get_active_state(model)
        assert state is not None
        assert state.name == "Locked"

    def test_time_sampled_wins_over_not_default(
        self, fresh_manager: ControlStateManager
    ) -> None:
        model = _build_model(
            is_time_sampled=True,
            is_authored=True,
            clear_values_supported=True,
        )
        state = fresh_manager.get_active_state(model)
        assert state is not None
        assert state.name == "TimeSampled"

    def test_not_default_fires_when_only_predicate_matching(
        self, fresh_manager: ControlStateManager
    ) -> None:
        model = _build_model(is_authored=True, clear_values_supported=True)
        state = fresh_manager.get_active_state(model)
        assert state is not None
        assert state.name == "NotDefault"


# ---------------------------------------------------------------------------
# Done-signal #3: no handler matches → None
# ---------------------------------------------------------------------------


class TestNoHandlerMatches:
    """When no predicate matches, ``get_active_state`` returns ``None``."""

    def test_unambiguous_unauthored_unlocked_returns_none(
        self, fresh_manager: ControlStateManager
    ) -> None:
        model = _build_model(is_authored=False)
        assert fresh_manager.get_active_state(model) is None

    def test_mock_adapter_authored_still_returns_none_for_not_default(
        self, fresh_manager: ControlStateManager
    ) -> None:
        """NotDefault is suppressed when ``clear_values`` is unsupported.

        Pinned so the "hidden when on_click is unavailable" rule survives
        future refactors.
        """
        model = _build_model(is_authored=True, clear_values_supported=False)
        assert fresh_manager.get_active_state(model) is None


# ---------------------------------------------------------------------------
# Done-signal #4: custom handler registration
# ---------------------------------------------------------------------------


class TestCustomRegistration:
    """Third-party code can register and cancel state handlers."""

    def test_register_inserts_by_priority(
        self, fresh_manager: ControlStateManager
    ) -> None:
        sub = fresh_manager.register_state(
            name="CustomHigh",
            predicate=lambda m: True,  # always matches
            icon_path="",
            priority=-1.0,  # beats Mixed(0)
            tooltip="custom",
        )
        try:
            names = [h.name for h in fresh_manager.list_states()]
            assert names[0] == "CustomHigh"
        finally:
            sub.cancel()

    def test_custom_handler_wins_over_builtin_at_lower_priority(
        self, fresh_manager: ControlStateManager
    ) -> None:
        sub = fresh_manager.register_state(
            name="CustomHigh",
            predicate=lambda m: True,
            icon_path="",
            priority=-1.0,
        )
        try:
            model = _build_model()
            state = fresh_manager.get_active_state(model)
            assert state is not None
            assert state.name == "CustomHigh"
        finally:
            sub.cancel()

    def test_custom_handler_loses_to_builtin_at_higher_priority(
        self, fresh_manager: ControlStateManager
    ) -> None:
        sub = fresh_manager.register_state(
            name="CustomLow",
            predicate=lambda m: True,
            icon_path="",
            priority=100.0,
        )
        try:
            model = _build_model(is_authored=True, clear_values_supported=True)
            state = fresh_manager.get_active_state(model)
            assert state is not None
            assert state.name == "NotDefault"  # priority 40 beats 100
        finally:
            sub.cancel()

    def test_cancel_removes_handler(
        self, fresh_manager: ControlStateManager
    ) -> None:
        sub = fresh_manager.register_state(
            name="Temporary",
            predicate=lambda m: True,
            icon_path="",
            priority=-10.0,
        )
        assert any(h.name == "Temporary" for h in fresh_manager.list_states())
        sub.cancel()
        assert not any(h.name == "Temporary" for h in fresh_manager.list_states())

    def test_cancel_is_idempotent(
        self, fresh_manager: ControlStateManager
    ) -> None:
        sub = fresh_manager.register_state(
            name="Once",
            predicate=lambda m: True,
            icon_path="",
            priority=-10.0,
        )
        sub.cancel()
        # Second cancel is a no-op; no exception.
        sub.cancel()

    def test_duplicate_name_raises(
        self, fresh_manager: ControlStateManager
    ) -> None:
        with pytest.raises(ValueError):
            fresh_manager.register_state(
                name="Mixed",  # already registered by defaults
                predicate=lambda m: True,
                icon_path="",
                priority=50.0,
            )


# ---------------------------------------------------------------------------
# Manager singleton semantics
# ---------------------------------------------------------------------------


class TestSingletonSemantics:
    def test_get_instance_returns_same_object(self) -> None:
        ControlStateManager._reset_for_tests()
        try:
            a = ControlStateManager.get_instance()
            b = ControlStateManager.get_instance()
            assert a is b
        finally:
            ControlStateManager._reset_for_tests()

    def test_defaults_registered_on_first_get_instance(self) -> None:
        ControlStateManager._reset_for_tests()
        try:
            mgr = ControlStateManager.get_instance()
            names = {h.name for h in mgr.list_states()}
            assert names == {"Mixed", "Locked", "TimeSampled", "NotDefault"}
        finally:
            ControlStateManager._reset_for_tests()

    def test_defaults_in_priority_order(self) -> None:
        ControlStateManager._reset_for_tests()
        try:
            mgr = ControlStateManager.get_instance()
            names = [h.name for h in mgr.list_states()]
            assert names == ["Mixed", "Locked", "TimeSampled", "NotDefault"]
        finally:
            ControlStateManager._reset_for_tests()

    def test_reset_clears_all_handlers(self) -> None:
        mgr = ControlStateManager.get_instance()
        assert len(mgr.list_states()) > 0
        ControlStateManager._reset_for_tests()
        # After reset, get_instance rebuilds a fresh one with defaults.
        mgr2 = ControlStateManager.get_instance()
        assert mgr2 is not mgr
        ControlStateManager._reset_for_tests()


# ---------------------------------------------------------------------------
# Predicates — unit coverage
# ---------------------------------------------------------------------------


class TestBuiltinPredicates:
    def test_mixed_predicate(self) -> None:
        ambiguous = _build_model(is_ambiguous=True)
        clean = _build_model()
        assert _mixed_predicate(ambiguous) is True
        assert _mixed_predicate(clean) is False

    def test_locked_predicate(self) -> None:
        assert _locked_predicate(_build_model(is_locked=True)) is True
        assert _locked_predicate(_build_model(is_locked=False)) is False

    def test_time_sampled_predicate(self) -> None:
        assert _time_sampled_predicate(_build_model(is_time_sampled=True)) is True
        assert _time_sampled_predicate(_build_model(is_time_sampled=False)) is False

    def test_not_default_requires_authored(self) -> None:
        assert (
            _not_default_predicate(
                _build_model(is_authored=False, clear_values_supported=True)
            )
            is False
        )

    def test_not_default_requires_clear_values_capability(self) -> None:
        assert (
            _not_default_predicate(
                _build_model(is_authored=True, clear_values_supported=False)
            )
            is False
        )

    def test_not_default_fires_when_authored_and_clear_supported(self) -> None:
        assert (
            _not_default_predicate(
                _build_model(is_authored=True, clear_values_supported=True)
            )
            is True
        )


class TestNotDefaultOnClick:
    """``_not_default_on_click`` forwards to ``adapter.clear_value``."""

    def test_calls_adapter_clear_value(self) -> None:
        calls: List[str] = []

        class _RecordingAdapter(MockPropertyAdapter):
            def clear_value(self, attr_name: str) -> None:
                calls.append(attr_name)

        adapter = _RecordingAdapter(
            paths=["/World/A"],
            attributes={"radius": _make_metadata()},
        )
        _not_default_on_click(adapter, "radius")
        assert calls == ["radius"]

    def test_propagates_not_implemented_from_adapter(self) -> None:
        """The bare click handler does NOT swallow the raise; the indicator
        does that at its own ``_on_click`` site. Keeps the wrapper
        honest — any caller that wants to re-use ``_not_default_on_click``
        sees the raw adapter error.
        """
        adapter = MockPropertyAdapter(
            paths=["/World/A"],
            attributes={"radius": _make_metadata()},
        )
        with pytest.raises(NotImplementedError):
            _not_default_on_click(adapter, "radius")


# ---------------------------------------------------------------------------
# Defensive behaviour
# ---------------------------------------------------------------------------


class TestBuggyPredicate:
    """A buggy predicate must not break neighbouring state resolution."""

    def test_raising_predicate_is_swallowed(
        self, fresh_manager: ControlStateManager
    ) -> None:
        def _raising(_m: Any) -> bool:
            raise RuntimeError("boom")

        sub = fresh_manager.register_state(
            name="Buggy",
            predicate=_raising,
            icon_path="",
            priority=-5.0,  # walked before Mixed(0)
        )
        try:
            model = _build_model(is_ambiguous=True)
            state = fresh_manager.get_active_state(model)
            # Mixed predicate still fires despite Buggy's raise.
            assert state is not None
            assert state.name == "Mixed"
        finally:
            sub.cancel()


# ---------------------------------------------------------------------------
# Handler dataclass
# ---------------------------------------------------------------------------


class TestControlStateHandlerDataclass:
    def test_is_frozen(self) -> None:
        handler = ControlStateHandler(
            name="X",
            predicate=lambda m: True,
            icon_path="",
            priority=1.0,
        )
        with pytest.raises((AttributeError, TypeError)):
            handler.name = "Y"  # type: ignore[misc]

    def test_optional_fields_default_to_none(self) -> None:
        handler = ControlStateHandler(
            name="X",
            predicate=lambda m: True,
            icon_path="",
            priority=1.0,
        )
        assert handler.on_click is None
        assert handler.tooltip is None
