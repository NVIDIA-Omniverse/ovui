/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <pybind11/pybind11.h>
#include <omni/ui/Types.h>

namespace omni
{
namespace ui
{

// Each backend (Kit adapter, standalone) provides its own implementation of this function.
// It is called at the end of PYBIND11_MODULE to register backend-specific bindings.
// Preserve the native renderer's Python enum identity at the backend boundary.
void registerPlatformPixelFormat(pybind11::module_& m);
PixelFormat pixelFormatFromPython(pybind11::handle value);
pybind11::object pixelFormatToPython(PixelFormat value);

// Convert only the native window handle; common window behavior is unchanged.
pybind11::object appWindowToPython(AppWindowHandle window);
AppWindowHandle appWindowFromPython(pybind11::handle window);

void registerPlatformBindings(pybind11::module_& m);

} // namespace ui
} // namespace omni
