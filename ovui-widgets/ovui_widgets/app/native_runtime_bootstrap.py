# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Native renderer bootstrap that is safe to import before ``omni.ui``.

Kit's OVRTX and OVStage Python packages share one Carbonite/plugin cohort.
OVRTX must create that framework first; importing the regular Application pulls
in UI modules and is therefore intentionally kept out of this module.
"""

from __future__ import annotations

import os
import sys
from importlib.metadata import entry_points
from typing import Any, Mapping

from ovui_widgets.common.error_reporter import ErrorReporter

_PROVIDER_ENV_NAMES = (
    "OVUI_DATA_ADAPTER_PROVIDER",
)
_ADAPTER_ENTRY_POINT_GROUP = "ovui_data_adapters.adapters"
_NATIVE_RENDERER_FACTORY_ENTRY_POINT_GROUP = (
    "ovui_data_adapters.native_renderer_factories"
)
_RENDERER_STARTUP_ENTRY_POINT_GROUP = "ovui_widgets.renderer_startup"
_NATIVE_TIMING_ENTRY_POINT_GROUP = "ovui_widgets.native_timing"


def _entry_points_for(group: str) -> tuple[Any, ...]:
    """Return installed entry points for ``group`` across metadata APIs."""

    try:
        return tuple(entry_points(group=group))
    except TypeError:  # pragma: no cover - compatibility with older metadata API
        discovered = entry_points()
        select = getattr(discovered, "select", None)
        if callable(select):
            return tuple(select(group=group))
        return tuple(discovered.get(group, ()))


def _selected_provider_name() -> str:
    selected = next(
        (
            os.environ[name].strip().lower()
            for name in _PROVIDER_ENV_NAMES
            if os.environ.get(name, "").strip()
        ),
        "",
    )
    if selected:
        return selected

    # Match AdapterRegistry's supported sole-provider auto-selection without
    # importing provider modules (which would initialize OVStage too early).
    points = _entry_points_for(_ADAPTER_ENTRY_POINT_GROUP)
    names = {str(point.name).strip().lower() for point in points}
    return "ovstage" if names == {"ovstage"} else ""


def _load_native_renderer_factory(provider_name: str) -> Any:
    """Load the one early-renderer factory published by ``provider_name``."""

    matches = tuple(
        point
        for point in _entry_points_for(_NATIVE_RENDERER_FACTORY_ENTRY_POINT_GROUP)
        if str(point.name).strip().lower() == provider_name
    )
    if not matches:
        raise LookupError(
            f"provider {provider_name!r} does not publish an early-renderer "
            f"factory in {_NATIVE_RENDERER_FACTORY_ENTRY_POINT_GROUP!r}"
        )
    if len(matches) != 1:
        raise RuntimeError(
            f"provider {provider_name!r} publishes {len(matches)} early-renderer "
            "factories; exactly one is required"
        )
    factory = matches[0].load()
    if not callable(factory):
        raise TypeError(
            f"provider {provider_name!r} early-renderer entry point is not callable"
        )
    return factory


def install_native_timing_hooks() -> bool:
    """Give the native timing table of an optional package to ``omni.ui``.

    Optional packages publish a callable in the ``ovui_widgets.native_timing``
    entry-point group. It returns a ``PyCapsule`` with the native function
    table, or ``None``. The application calls this before ``ui.init`` so that
    the native start-up phases (for example Vulkan Init and ImGui Init) are
    measured too. Without such a package the native scopes stay empty.

    Returns ``True`` when a table was installed.
    """
    points = _entry_points_for(_NATIVE_TIMING_ENTRY_POINT_GROUP)
    if not points:
        return False

    import omni.ui as ui

    set_hooks = getattr(getattr(ui, "_ui", None), "_set_native_timing_hooks", None)
    if not callable(set_hooks):
        return False
    for point in points:
        try:
            capsule = point.load()()
        except Exception as exc:
            ErrorReporter.log_warning(
                "Native Runtime Bootstrap",
                f"native timing hook {point.name!r} failed: "
                f"{type(exc).__name__}: {exc}",
            )
            continue
        if capsule is None:
            continue
        try:
            set_hooks(capsule)
        except Exception as exc:
            ErrorReporter.log_warning(
                "Native Runtime Bootstrap",
                f"native timing hook {point.name!r} was refused: "
                f"{type(exc).__name__}: {exc}",
            )
            continue
        return True
    return False


def run_renderer_startup_hooks(settings: Mapping[str, Any], renderer: Any) -> None:
    """Call each optional component's renderer startup hook once.

    Optional packages publish ``(settings, renderer)`` callables in the
    ``ovui_widgets.renderer_startup`` entry-point group. A failed hook is
    logged and does not stop renderer startup.
    """
    for point in _entry_points_for(_RENDERER_STARTUP_ENTRY_POINT_GROUP):
        try:
            point.load()(settings, renderer)
        except Exception as exc:
            ErrorReporter.log_warning(
                "Native Runtime Bootstrap",
                f"renderer startup hook {point.name!r} failed: "
                f"{type(exc).__name__}: {exc}",
            )


def preconstruct_selected_native_renderer(
    settings: Mapping[str, Any] | None = None,
) -> tuple[bool, Any | None]:
    """Construct OVRTX before UI/OVStage when the ovstage provider is selected.

    Returns ``(attempted, renderer)``. ``attempted`` lets callers distinguish a
    completed bootstrap from an unrelated provider. The OVStage provider has
    no read-only compatibility path: failure to construct its BORROW renderer
    is fatal before UI or OVStage initialization.
    """
    selected = _selected_provider_name()
    if selected != "ovstage":
        return False, None

    settings = settings or {}
    try:
        factory = _load_native_renderer_factory(selected)
        renderer = factory()
        run_renderer_startup_hooks(settings, renderer)
        return True, renderer
    except Exception as exc:
        raise RuntimeError(
            "OVRTX must initialize before omni.ui/OVStage for the ovstage "
            f"provider ({type(exc).__name__}: {exc})"
        ) from exc


def install_preconstructed_renderer(app: Any, bootstrap: tuple[bool, Any | None]) -> None:
    """Transfer an early renderer (or an attempted ``None``) to Application."""
    attempted, renderer = bootstrap
    if attempted:
        app._renderer_startup_hooks_complete = True
        bind_undo = getattr(renderer, "set_undo_manager", None)
        if callable(bind_undo):
            bind_undo(getattr(app, "undo_manager", None))
        app._startup_prebuilt_renderer = renderer
