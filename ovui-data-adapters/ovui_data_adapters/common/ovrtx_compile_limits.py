# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Limit the number of parallel shader compiler sessions of the native renderer.

The first native step compiles every material. The native renderer starts as
many compiler sessions as its estimate of free system memory allows (15 on a
128 GB host), and each session adds host memory. Measured with the renderer of
the USD Workbench container on a four-material scene, cold caches: 15 sessions
peaked at 19.1 GiB RSS, 2 sessions at 11.8 GiB.

Control, read before the first renderer is created:

``OVUI_SHADER_COMPILER_SESSIONS``
    ``<n>`` (1 or more): use at most ``n`` sessions.
    unset, empty or ``native``: do not change the renderer's own choice.

Nothing is changed unless the variable is set: fewer sessions use less host
memory but compile more slowly, so the default keeps the renderer's choice.
The documented minimum host memory for a scene size (``render_diagnostics``)
says when to set it.

The setting is the renderer's ``/gpu/shadercompiler/warmcountMax`` and
``/gpu/shadercompiler/warmcount``. It only has effect for the first renderer of
a process, because the renderer reads it when its compiler starts. The settings
can be given only to a loaded renderer library, so the library is loaded and
initialized first. The library is initialized once for the process, with a
renderer config; it gets the config of the renderer that is created next, as
that renderer would give it, not an empty one.
"""

from __future__ import annotations

import ctypes
import logging
import os
from typing import Any, Optional

LOGGER = logging.getLogger("ovui.render_diagnostics")

SESSIONS_ENV = "OVUI_SHADER_COMPILER_SESSIONS"

_EXTENSION = b"ovrtx.settings.apply_settings"


def compile_sessions(environ: Optional[dict] = None) -> Optional[int]:
    """Return the session limit to apply, or None to keep the renderer's choice."""

    value = (environ if environ is not None else os.environ).get(SESSIONS_ENV, "").strip().lower()
    if not value or value == "native":
        return None
    try:
        count = int(value)
    except ValueError:
        count = 0
    if count >= 1:
        return count
    LOGGER.warning("%s=%r is not 'native' or a number of 1 or more; the renderer's own choice is kept", SESSIONS_ENV, value)
    return None


def apply_setting_tokens(tokens: list[str], config: Any = None) -> str:
    """Publish ``--/key=value`` tokens through the renderer's settings extension.

    ``config`` is the ``RendererConfig`` of the renderer that is created next (None: the default config). A library
    that is not loaded yet is initialized with it. Returns "" on success, else the reason. Never raises.
    """

    try:
        from ovui_data_adapters.common.ovrtx_import import import_ovrtx

        imported = import_ovrtx()
        if imported.module is None:
            return f"ovrtx is not available ({imported.error})"
        # The ctypes bindings of the loaded copy (``import ovrtx`` loads them): nothing else is imported.
        bindings = getattr(getattr(imported.module, "_src", None), "bindings", None)
        if bindings is None:
            return "the loaded ovrtx has no ctypes bindings (ovrtx._src.bindings)"

        loader = bindings._ovrtx_loader
        if loader._lib is None:
            module = imported.module
            to_c_config = getattr(getattr(module, "Renderer", None), "_to_c_config", None)
            if not callable(to_c_config):
                return "this ovrtx cannot convert a renderer config (ovrtx.Renderer._to_c_config)"
            loader.create_bindings(to_c_config(config if config is not None else module.RendererConfig()))
        lib = loader._lib
        lib.ovrtx_query_extension.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
        lib.ovrtx_query_extension.restype = bindings.ovrtx_result_t
        pointer = ctypes.c_void_p()
        query = lib.ovrtx_query_extension(_EXTENSION, ctypes.byref(pointer))
        if query.status != bindings.OVRTX_API_SUCCESS or not pointer:
            return "this ovrtx has no 'ovrtx.settings.apply_settings' extension"

        class _VTable(ctypes.Structure):
            _fields_ = [("apply_settings", ctypes.CFUNCTYPE(bindings.ovrtx_result_t, bindings.ovx_string_t))]

        vtable = ctypes.cast(pointer, ctypes.POINTER(_VTable)).contents
        for token in tokens:
            if vtable.apply_settings(bindings.ovx_string_t(token)).status != bindings.OVRTX_API_SUCCESS:
                return f"apply_settings({token!r}) failed"
        return ""
    except Exception as exc:  # noqa: BLE001 - a missing control must not stop the renderer
        return f"{type(exc).__name__}: {exc}"


def limit_shader_compile_sessions(config: Any = None) -> Optional[int]:
    """Apply the session limit of ``OVUI_SHADER_COMPILER_SESSIONS`` before the first renderer is created.

    ``config`` is the ``RendererConfig`` of that renderer, complete (see :func:`apply_setting_tokens`). Returns the
    limit applied, or None. Without the setting nothing is imported or changed.
    """

    count = compile_sessions()
    if count is None:
        return None
    error = apply_setting_tokens([
        f"--/gpu/shadercompiler/warmcountMax={count}",
        f"--/gpu/shadercompiler/warmcount={count}",
    ], config)
    if error:
        LOGGER.warning("could not limit shader compiler sessions to %d: %s", count, error)
        return None
    LOGGER.info("shader compiler sessions limited to %d (%s)", count, SESSIONS_ENV)
    return count
