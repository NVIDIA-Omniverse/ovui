/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "../Api.h"
#include "../Types.h"

// CPython's object type, declared without including Python.h: the core stores
// these hooks but never calls into Python itself.
struct _object;

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Host-specific parts of the `omni.ui._ui` Python module.
 *
 * The `_ui` module is the same binary in every host. A host (a host plugin,
 * or the standalone backend of the wheel) registers these hooks before Python
 * imports `omni.ui`; `_ui` calls them, and falls back to host-neutral defaults
 * for any hook that is not set. Python objects are passed as `PyObject*`.
 * Hooks may raise by throwing the pybind11 exceptions of the module's
 * pybind11 version; the host is built with the same pybind11 and compiler.
 */
struct PlatformHooks
{
    /// Called at the end of `_ui` initialisation to add host functions to the module.
    void (*registerPlatformBindings)(_object* module) = nullptr;
    /// Sets `TextureFormat` / `PixelFormat` on the module.
    void (*registerPlatformPixelFormat)(_object* module) = nullptr;
    /// Converts a Python value to a pixel format.
    PixelFormat (*pixelFormatFromPython)(_object* value) = nullptr;
    /// Returns a new reference to the Python value of a pixel format.
    _object* (*pixelFormatToPython)(PixelFormat value) = nullptr;
    /// Returns a new reference to the Python object of a native window handle.
    _object* (*appWindowToPython)(AppWindowHandle window) = nullptr;
    /// Converts a Python window object to its native handle.
    AppWindowHandle (*appWindowFromPython)(_object* window) = nullptr;
};

/// Registers the host's hooks. The pointed-to struct must outlive the registration.
OMNIUI_API void setPlatformHooks(const PlatformHooks* hooks);
/// Removes the registered hooks; `_ui` uses its host-neutral defaults again.
OMNIUI_API void resetPlatformHooks();
/// The registered hooks, or nullptr.
OMNIUI_API const PlatformHooks* getPlatformHooks();

OMNIUI_NAMESPACE_CLOSE_SCOPE
