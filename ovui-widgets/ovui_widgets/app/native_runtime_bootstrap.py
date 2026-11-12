# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Native renderer bootstrap that is safe to import before ``omni.ui``.

A data-adapter provider can need its renderer to create the process-wide
plugin framework first. Importing the regular Application pulls in UI modules
and is therefore intentionally kept out of this module.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from importlib.metadata import entry_points
from typing import Any, Mapping

from ovui_data_adapters.common import AdapterRegistry
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
_NATIVE_PACING_ENTRY_POINT_GROUP = "ovui_widgets.native_pacing"


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
    # importing provider modules (which would initialize them too early).
    points = _entry_points_for(_ADAPTER_ENTRY_POINT_GROUP)
    names = {str(point.name).strip().lower() for point in points}
    return next(iter(names)) if len(names) == 1 else ""


def _load_native_renderer_factory(provider_name: str) -> Any | None:
    """Return the early-renderer factory that ``provider_name`` registers.

    Every entry point in the ``ovui_data_adapters.native_renderer_factories``
    group names a function that registers its provider. All of them are called,
    so one provider's early renderer does not hide another's registration.

    A registration that fails tells the application that the provider is broken:
    if ``provider_name`` reports a load failure, or raises while registering,
    this raises with that cause. Another provider's registration failure does
    not stop start-up, but it is reported. A provider that registers no early
    renderer and reports no failure needs none, and this returns ``None``.
    """

    registry = AdapterRegistry()
    for point in _entry_points_for(_NATIVE_RENDERER_FACTORY_ENTRY_POINT_GROUP):
        name = str(point.name).strip().lower()
        try:
            point.load()(registry)
        except Exception as exc:  # a broken registration is a reported failure
            registry.report_module_load_failure(name, str(getattr(point, "value", "")), exc)

    selected_failures = []
    for failure in registry.load_failures:
        if str(failure.name).strip().lower() == provider_name:
            selected_failures.append(failure)
        else:
            # Another provider's failure is reported but does not stop start-up.
            ErrorReporter.log_warning(
                "native_runtime_bootstrap",
                f"early-renderer registration of provider {failure.name!r} failed: "
                f"{failure.message}",
            )
    if selected_failures:
        raise RuntimeError(
            f"provider {provider_name!r} failed to register its early renderer: "
            + "; ".join(failure.message for failure in selected_failures)
        )

    providers = [
        provider for provider in registry.available_adapters()
        if str(provider.name).strip().lower() == provider_name
    ]
    if not providers:
        return None
    if len(providers) != 1:
        raise RuntimeError(
            f"provider {provider_name!r} registers {len(providers)} early-renderer "
            "providers; exactly one is required"
        )
    factory = providers[0].factories.renderer
    if not callable(factory):
        raise TypeError(
            f"provider {provider_name!r} registers no callable early-renderer factory"
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


class FrameSourceRegistry:
    """What the ``ovui_widgets.native_pacing`` register functions add to."""

    def __init__(self) -> None:
        self.frame_sources: list[tuple[str, Any]] = []
        self._point_name = ""

    def add_frame_source(self, capsule: Any) -> None:
        """Add a ``PyCapsule`` with a renderer table for ovui's frame-pacing slot."""

        self.frame_sources.append((self._point_name, capsule))


def install_native_frame_pacing_hooks() -> bool:
    """Give the renderer table of an optional package to ``omni.ui``.

    ovui owns the image slots, the CUDA/Vulkan upload and the present worker;
    the table brings the render worker and every renderer call. Each entry
    point of the ``ovui_widgets.native_pacing`` group names a register
    function, which takes a :class:`FrameSourceRegistry` and adds its tables.
    Every entry point is called. The application calls this before
    ``ui.init``, so the first viewport session can already use it. ovui has one
    slot: the first table it accepts is installed. Without such a package the
    slot stays empty and ovui presents the viewport on the ordinary UI tick.

    Returns ``True`` when a table was installed.
    """
    points = _entry_points_for(_NATIVE_PACING_ENTRY_POINT_GROUP)
    if not points:
        return False

    import omni.ui as ui

    set_hooks = getattr(getattr(ui, "_ui", None), "_set_native_frame_pacing_hooks", None)
    if not callable(set_hooks):
        return False
    registry = FrameSourceRegistry()
    for point in points:
        registry._point_name = point.name
        try:
            point.load()(registry)
        except Exception as exc:
            ErrorReporter.log_warning(
                "Native Runtime Bootstrap",
                f"native frame pacing hook {point.name!r} failed: "
                f"{type(exc).__name__}: {exc}",
            )
    for name, capsule in registry.frame_sources:
        try:
            set_hooks(capsule)
        except Exception as exc:
            ErrorReporter.log_warning(
                "Native Runtime Bootstrap",
                f"native frame pacing hook {name!r} was refused: "
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


def limit_openusd_work_threads() -> None:
    """Size the OpenUSD work thread pool to the CPUs that this process may use.

    OpenUSD sizes its pool to the CPUs of the host when it first runs parallel
    work, and an optional component can do that while it loads. A container
    with a CPU quota then runs one thread for each host CPU, and each new open
    of a large scene leaves memory in all of them. The limit goes through
    OpenUSD's own ``PXR_WORK_THREAD_LIMIT`` before anything loads OpenUSD, so
    this imports neither OpenUSD nor a provider. A value set by the user is
    kept. Without an installed OpenUSD, or when OpenUSD is already loaded,
    nothing changes.
    """

    if os.environ.get("PXR_WORK_THREAD_LIMIT") or "pxr" in sys.modules:
        return
    if importlib.util.find_spec("pxr") is None:
        return  # No OpenUSD in this environment: there is no pool to size.
    from ovui_data_adapters.common.cpu_budget import usable_cpu_count

    usable = usable_cpu_count()
    host = os.cpu_count()
    if usable is None or host is None or usable >= host:
        return
    os.environ["PXR_WORK_THREAD_LIMIT"] = str(usable)
    print(
        f"[ovui_widgets.app] OpenUSD work threads: {usable}, the CPUs that this process "
        f"may use (the host has {host})",
        file=sys.stderr,
    )


def preconstruct_selected_native_renderer(
    settings: Mapping[str, Any] | None = None,
) -> tuple[bool, Any | None]:
    """Construct the renderer before UI when the selected provider needs it.

    A provider declares this need by registering an early-renderer factory
    through the ``ovui_data_adapters.native_renderer_factories`` group.
    Returns ``(attempted, renderer)``. ``attempted`` lets callers distinguish a
    completed bootstrap from a provider without that need. Failure to construct
    a declared early renderer is fatal before UI initialization.
    """
    selected = _selected_provider_name()
    if not selected:
        return False, None

    settings = settings or {}
    try:
        factory = _load_native_renderer_factory(selected)
        if factory is None:
            return False, None
        renderer = factory()
        run_renderer_startup_hooks(settings, renderer)
        return True, renderer
    except Exception as exc:
        raise RuntimeError(
            f"the renderer of provider {selected!r} must initialize before "
            f"omni.ui ({type(exc).__name__}: {exc})"
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
