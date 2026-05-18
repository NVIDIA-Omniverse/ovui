/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#pragma once

#include <pybind11/pybind11.h>

namespace omni
{
namespace ui
{

// Each backend (Kit adapter, standalone) provides its own implementation of this function.
// It is called at the end of PYBIND11_MODULE to register backend-specific bindings.
void registerPlatformBindings(pybind11::module_& m);

} // namespace ui
} // namespace omni
