/*
 * SPDX-FileCopyrightText: Copyright (c) 2022-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
#include <pybind11/functional.h>

#include <omni/ui/ImageProvider/DynamicTextureProvider.h>

#include <memory>
#include <string>

namespace py = pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapDynamicTextureProvider(py::module& m)
{
    py::class_<DynamicTextureProvider, ByteImageProvider, std::shared_ptr<DynamicTextureProvider>>(m, "DynamicTextureProvider", "doc")
        .def(py::init([](const std::string& textureName) {
            pybind11::gil_scoped_release gil;
            return ImageProvider::create<DynamicTextureProvider>(textureName);
        }), "doc")
        /**/;
}
