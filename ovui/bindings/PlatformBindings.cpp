/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

// The host boundary of the shared `_ui` module: each function calls the hook
// the host registered (omni/ui/bind/PlatformHooks.h) or, without one, a
// host-neutral default.

#include "PlatformBindings.h"

#include <omni/ui/bind/PlatformHooks.h>

namespace omni
{
namespace ui
{

pybind11::object appWindowToPython(AppWindowHandle window)
{
    const auto* hooks = getPlatformHooks();
    if (hooks && hooks->appWindowToPython)
    {
        PyObject* result = hooks->appWindowToPython(window);
        if (!result)
            throw pybind11::error_already_set();
        return pybind11::reinterpret_steal<pybind11::object>(result);
    }
    return pybind11::cast(window);
}

AppWindowHandle appWindowFromPython(pybind11::handle window)
{
    const auto* hooks = getPlatformHooks();
    if (hooks && hooks->appWindowFromPython)
        return hooks->appWindowFromPython(window.ptr());
    return pybind11::cast<AppWindowHandle>(window);
}

PixelFormat pixelFormatFromPython(pybind11::handle value)
{
    const auto* hooks = getPlatformHooks();
    if (hooks && hooks->pixelFormatFromPython)
        return hooks->pixelFormatFromPython(value.ptr());
    return pybind11::cast<PixelFormat>(value);
}

pybind11::object pixelFormatToPython(PixelFormat value)
{
    const auto* hooks = getPlatformHooks();
    if (hooks && hooks->pixelFormatToPython)
    {
        PyObject* result = hooks->pixelFormatToPython(value);
        if (!result)
            throw pybind11::error_already_set();
        return pybind11::reinterpret_steal<pybind11::object>(result);
    }
    return pybind11::cast(value);
}

void registerPlatformPixelFormat(pybind11::module_& m)
{
    const auto* hooks = getPlatformHooks();
    if (hooks && hooks->registerPlatformPixelFormat)
    {
        hooks->registerPlatformPixelFormat(m.ptr());
        return;
    }
    // Exposed as "TextureFormat" for backward compatibility with
    // omni.gpu_foundation_factory.TextureFormat used by existing Kit code.
    pybind11::enum_<PixelFormat>(m, "TextureFormat")
        .value("UNKNOWN", PixelFormat::eUnknown)
        .value("RGBA8_UNORM", PixelFormat::eRGBA8_UNORM)
        .value("RGBA8_SRGB", PixelFormat::eRGBA8_SRGB)
        .value("BGRA8_UNORM", PixelFormat::eBGRA8_UNORM)
        .value("R8_UNORM", PixelFormat::eR8_UNORM)
        .value("RGBA16_FLOAT", PixelFormat::eRGBA16_FLOAT)
        .value("RGBA32_FLOAT", PixelFormat::eRGBA32_FLOAT)
        .value("R16_FLOAT", PixelFormat::eR16_FLOAT)
        .value("R32_FLOAT", PixelFormat::eR32_FLOAT)
        .value("RG16_FLOAT", PixelFormat::eRG16_FLOAT)
        .value("RG32_FLOAT", PixelFormat::eRG32_FLOAT)
        .value("RGB16_FLOAT", PixelFormat::eRGB16_FLOAT)
        .value("RGB32_FLOAT", PixelFormat::eRGB32_FLOAT);
}

void registerPlatformBindings(pybind11::module_& m)
{
    const auto* hooks = getPlatformHooks();
    if (hooks && hooks->registerPlatformBindings)
        hooks->registerPlatformBindings(m.ptr());
}

} // namespace ui
} // namespace omni
