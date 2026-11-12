# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Carb settings for the ovrtx runtime, applied before a renderer is created.

``ovrtx.RendererConfig`` has no field for a generic Carb setting. Some plugin
settings, for example ``/persistent/app/material/materialx/disableDeduplication``
of the MaterialX plugin, are read when the plugin generates its first material.
They must be set before the first renderer exists.

This module reads the environment variable ``OVUI_OVRTX_CARB_SETTINGS`` and
publishes each entry through the ovrtx extension ``ovrtx.settings.apply_settings``.
Both data adapters call :func:`apply_environment_carb_settings` right before they
create an ``ovrtx.Renderer``, with the config of that renderer. A host application
can call :func:`apply_carb_settings` itself.

The settings can be given only to a loaded renderer library. When the library is
not loaded yet, it is loaded and initialized with the config of the renderer that
is created next, as that renderer would initialize it, not with an empty config:
ovrtx reads some options (for example its cache root) only from the config of the
first initialization.

Format of the variable: entries ``/path/to/key=value``, separated by new lines or
semicolons. A leading ``--`` on an entry is accepted. A value is passed to Carb
unchanged: ``true``, ``false``, a number, or a string.

A setting that cannot be applied raises :class:`OvrtxCarbSettingsError`. The
settings are never skipped silently.

:func:`read_carb_bool` reads a bool Carb setting of the loaded renderer library
through the ovrtx extension ``ovrtx.settings.read_settings.v1``.
"""

from __future__ import annotations

import ctypes
import importlib
import logging
import os
import re
from typing import Any, Iterable, Optional, Tuple

OVRTX_CARB_SETTINGS_ENV = "OVUI_OVRTX_CARB_SETTINGS"

#: Extension name from ``ovrtx_settings.h`` (``OVRTX_EXTENSION_APPLY_SETTINGS``).
_APPLY_SETTINGS_EXTENSION = b"ovrtx.settings.apply_settings"
#: Extension name from ``ovrtx_settings.h`` (``OVRTX_EXTENSION_READ_SETTINGS_V1``).
_READ_SETTINGS_EXTENSION = b"ovrtx.settings.read_settings.v1"
#: ``ovrtx_setting_type_t`` value of a bool setting.
_SETTING_TYPE_BOOL = 1

#: Capability check: an older ovrtx does not apply ``disableDeduplication``.
_MATERIALX_DEDUPLICATION_FIX_VERSION = (0, 5, 0)
_MATERIALX_DEDUPLICATION_KEY = "/persistent/app/material/materialx/disableDeduplication"

_LOGGER = logging.getLogger(__name__)
_ENTRY_SEPARATOR_RE = re.compile(r"[;\r\n]+")
_KEY_RE = re.compile(r"^/[^\s=]+$")


class OvrtxCarbSettingsError(RuntimeError):
    """A Carb setting for ovrtx is malformed or could not be applied."""


def parse_carb_settings(text: str) -> Tuple[str, ...]:
    """Return the ``--/key=value`` tokens for the entries in ``text``.

    Raises :class:`OvrtxCarbSettingsError` that names the bad entry.
    """

    tokens = []
    for raw_entry in _ENTRY_SEPARATOR_RE.split(text or ""):
        entry = raw_entry.strip()
        if not entry:
            continue
        if entry.startswith("--"):
            entry = entry[2:]
        key, separator, value = entry.partition("=")
        key = key.strip()
        value = value.strip()
        if not separator or not _KEY_RE.match(key) or not value:
            raise OvrtxCarbSettingsError(
                f"Cannot read the ovrtx Carb setting {raw_entry.strip()!r} from "
                f"{OVRTX_CARB_SETTINGS_ENV}: write it as /path/to/key=value."
            )
        tokens.append(f"--{key}={value}")
    return tuple(tokens)


def _start_renderer_library(ovrtx: Any, loader: Any, token: str, config: Any) -> None:
    """Load and initialize the renderer library with ``config``, as ``ovrtx.Renderer(config)`` would."""

    to_c_config = getattr(getattr(ovrtx, "Renderer", None), "_to_c_config", None)
    if not callable(to_c_config):
        raise OvrtxCarbSettingsError(
            f"Cannot apply the ovrtx Carb setting {token!r}: the installed ovrtx cannot "
            f"convert a renderer config ({ovrtx.__name__}.Renderer._to_c_config is missing)."
        )
    loader.create_bindings(to_c_config(config if config is not None else ovrtx.RendererConfig()))


def _publish_with_ovrtx_extension(ovrtx: Any, token: str, config: Any = None) -> None:
    """Publish one token through ``ovrtx.settings.apply_settings``.

    ``config`` is the ``RendererConfig`` of the renderer that is created next (None: the default config).
    """

    try:
        # The same ovrtx copy that the caller loaded (OVRTX_ROOT can select one).
        bindings = importlib.import_module(f"{ovrtx.__name__}._src.bindings")
    except ImportError as error:
        raise OvrtxCarbSettingsError(
            f"Cannot apply the ovrtx Carb setting {token!r}: the installed ovrtx "
            f"has no ctypes binding module ({ovrtx.__name__}._src.bindings): {error}."
        ) from error
    loader = bindings._ovrtx_loader
    if loader._lib is None:
        _start_renderer_library(ovrtx, loader, token, config)
    lib = loader._lib
    lib.ovrtx_query_extension.argtypes = [
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    lib.ovrtx_query_extension.restype = bindings.ovrtx_result_t
    lib.ovrtx_get_last_error.argtypes = []
    lib.ovrtx_get_last_error.restype = bindings.ovx_string_t
    pointer = ctypes.c_void_p()
    query = lib.ovrtx_query_extension(_APPLY_SETTINGS_EXTENSION, ctypes.byref(pointer))
    if query.status != bindings.OVRTX_API_SUCCESS or not pointer:
        raise OvrtxCarbSettingsError(
            f"Cannot apply the ovrtx Carb setting {token!r}: this ovrtx build has no "
            f"'ovrtx.settings.apply_settings' extension ({lib.ovrtx_get_last_error()})."
        )

    class _VTable(ctypes.Structure):
        _fields_ = [
            (
                "apply_settings",
                ctypes.CFUNCTYPE(bindings.ovrtx_result_t, bindings.ovx_string_t),
            ),
        ]

    vtable = ctypes.cast(pointer, ctypes.POINTER(_VTable)).contents
    result = vtable.apply_settings(bindings.ovx_string_t(token))
    if result.status != bindings.OVRTX_API_SUCCESS:
        raise OvrtxCarbSettingsError(
            f"The ovrtx Carb setting {token!r} was rejected: {lib.ovrtx_get_last_error()}."
        )


#: The ``ovrtx_extension_read_settings_v1_t`` type of each ovrtx binding module. ctypes keeps
#: each structure type and its pointer type for the life of the process, so the type is made once.
_READ_VTABLE_TYPES: dict = {}


def _read_vtable_type(bindings: Any) -> type:
    """The first fields of ``ovrtx_extension_read_settings_v1_t`` for the ctypes types of ``bindings``."""

    vtable_type = _READ_VTABLE_TYPES.get(bindings.__name__)
    if vtable_type is None:

        class _ReadVTable(ctypes.Structure):
            _fields_ = [
                ("abi_version", ctypes.c_uint32),
                ("struct_size", ctypes.c_uint32),
                (
                    "get_type",
                    ctypes.CFUNCTYPE(bindings.ovrtx_result_t, bindings.ovx_string_t, ctypes.POINTER(ctypes.c_int)),
                ),
                (
                    "get_bool",
                    ctypes.CFUNCTYPE(bindings.ovrtx_result_t, bindings.ovx_string_t, ctypes.POINTER(ctypes.c_bool)),
                ),
            ]

        vtable_type = _READ_VTABLE_TYPES[bindings.__name__] = _ReadVTable
    return vtable_type


def read_carb_bool(ovrtx: Any, key: str) -> Optional[bool]:
    """Return the Carb setting ``key`` of the loaded renderer library when it is a bool.

    Reads through the ovrtx extension ``ovrtx.settings.read_settings.v1``. Returns None
    when the setting is not a bool. Raises :class:`OvrtxCarbSettingsError`, with the
    cause, when the setting cannot be read: the ovrtx binding module does not load, the
    renderer library is not loaded, this ovrtx has no such extension or another form of
    it, or the read fails.
    """

    module = f"{ovrtx.__name__}._src.bindings"
    try:
        bindings = importlib.import_module(module)
    except ImportError as error:
        raise OvrtxCarbSettingsError(
            f"Cannot read the ovrtx Carb setting {key!r}: the module {module} does not load: {error}."
        ) from error
    loader = getattr(bindings, "_ovrtx_loader", None)
    lib = getattr(loader, "_lib", None)
    if lib is None:
        raise OvrtxCarbSettingsError(
            f"Cannot read the ovrtx Carb setting {key!r}: the renderer library of {module} is not loaded."
        )
    lib.ovrtx_query_extension.argtypes = [
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    lib.ovrtx_query_extension.restype = bindings.ovrtx_result_t
    lib.ovrtx_get_last_error.argtypes = []
    lib.ovrtx_get_last_error.restype = bindings.ovx_string_t
    pointer = ctypes.c_void_p()
    query = lib.ovrtx_query_extension(_READ_SETTINGS_EXTENSION, ctypes.byref(pointer))
    if query.status != bindings.OVRTX_API_SUCCESS or not pointer:
        raise OvrtxCarbSettingsError(
            f"Cannot read the ovrtx Carb setting {key!r}: this ovrtx has no extension "
            f"{_READ_SETTINGS_EXTENSION.decode()}."
        )

    vtable_type = _read_vtable_type(bindings)
    vtable = ctypes.cast(pointer, ctypes.POINTER(vtable_type)).contents
    if vtable.abi_version != 1 or vtable.struct_size < ctypes.sizeof(vtable_type):
        raise OvrtxCarbSettingsError(
            f"Cannot read the ovrtx Carb setting {key!r}: the extension "
            f"{_READ_SETTINGS_EXTENSION.decode()} has ABI version {vtable.abi_version} and size "
            f"{vtable.struct_size}; this reader needs ABI version 1 and size {ctypes.sizeof(vtable_type)} or more."
        )
    name = bindings.ovx_string_t(key)
    setting_type = ctypes.c_int(0)
    result = vtable.get_type(name, ctypes.byref(setting_type))
    if result.status != bindings.OVRTX_API_SUCCESS:
        raise OvrtxCarbSettingsError(f"Cannot read the ovrtx Carb setting {key!r}: {lib.ovrtx_get_last_error()}.")
    if setting_type.value != _SETTING_TYPE_BOOL:
        return None
    value = ctypes.c_bool(False)
    result = vtable.get_bool(name, ctypes.byref(value))
    if result.status != bindings.OVRTX_API_SUCCESS:
        raise OvrtxCarbSettingsError(f"Cannot read the ovrtx Carb setting {key!r}: {lib.ovrtx_get_last_error()}.")
    return bool(value.value)


def apply_carb_settings(ovrtx: Any, tokens: Iterable[str], config: Any = None) -> Tuple[str, ...]:
    """Publish ``tokens`` (from :func:`parse_carb_settings`) to the ovrtx runtime.

    Call this before the first ``ovrtx.Renderer`` is created, with the ``RendererConfig``
    of that renderer (None: the default config). Returns the tokens that were applied.
    """

    applied = []
    for token in tokens:
        _publish_with_ovrtx_extension(ovrtx, token, config)
        _LOGGER.info("Applied the ovrtx Carb setting %s", token)
        applied.append(token)
        if token.startswith(f"--{_MATERIALX_DEDUPLICATION_KEY}="):
            _warn_if_deduplication_setting_is_ignored(ovrtx)
    return tuple(applied)


def _warn_if_deduplication_setting_is_ignored(ovrtx: Any) -> None:
    version = str(getattr(ovrtx, "__version__", ""))
    try:
        numbers = tuple(int(part) for part in version.split(".")[:3])
    except ValueError:
        return
    if numbers < _MATERIALX_DEDUPLICATION_FIX_VERSION:
        _LOGGER.warning(
            "ovrtx %s ignores %s. MaterialX materials with the same graph still share one "
            "generated module. Use an ovrtx that applies this setting.",
            version,
            _MATERIALX_DEDUPLICATION_KEY,
        )


def apply_environment_carb_settings(ovrtx: Any, config: Any = None) -> Tuple[str, ...]:
    """Apply the settings in ``OVUI_OVRTX_CARB_SETTINGS``, if the variable is set.

    ``config`` is the ``RendererConfig`` of the renderer that is created next. The
    settings are process-global and are applied again on each call, so a renderer
    that is created later still sees them. Without the variable, nothing is loaded
    or changed.
    """

    tokens = parse_carb_settings(os.environ.get(OVRTX_CARB_SETTINGS_ENV, ""))
    if not tokens:
        return ()
    return apply_carb_settings(ovrtx, tokens, config)
