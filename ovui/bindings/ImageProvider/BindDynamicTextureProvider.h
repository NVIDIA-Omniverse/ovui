/*
 * SPDX-FileCopyrightText: Copyright (c) 2022-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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
