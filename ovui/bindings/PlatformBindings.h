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

// Parameters that take any Python object for the host to convert. Help text
// and TypeError messages name the type that ovui itself accepts.
struct PixelFormatObject : pybind11::object
{
    using pybind11::object::object;
    static bool check_(pybind11::handle) { return true; }
};
struct AppWindowObject : pybind11::object
{
    using pybind11::object::object;
    static bool check_(pybind11::handle) { return true; }
};

} // namespace ui
} // namespace omni

template <>
struct pybind11::detail::handle_type_name<omni::ui::PixelFormatObject>
{
    static constexpr auto name = make_caster<omni::ui::PixelFormat>::name;
};
template <>
struct pybind11::detail::handle_type_name<omni::ui::AppWindowObject>
{
    static constexpr auto name = make_caster<omni::ui::AppWindowHandle>::name;
};
