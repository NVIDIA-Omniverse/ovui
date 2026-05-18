/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include <omni/ui/Types.h>
#include <omni/ui/bind/BindUtils.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapPixelFormat(module& m)
{
    // Exposed as "TextureFormat" for backward compatibility with
    // omni.gpu_foundation_factory.TextureFormat used by existing Kit code.
    enum_<PixelFormat>(m, "TextureFormat")
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
