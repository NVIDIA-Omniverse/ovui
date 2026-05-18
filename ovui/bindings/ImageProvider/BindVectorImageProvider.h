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

#include <omni/ui/ImageProvider/VectorImageProvider.h>
#include <omni/ui/bind/BindUtils.h>

#include <memory>
#include <string>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapVectorImageProvider(module& m)
{
    class_<VectorImageProvider, ImageProvider, std::shared_ptr<VectorImageProvider>>(m, "VectorImageProvider", "doc")
        .def(init([](const char* source_url, kwargs kwargs) {
            pybind11::gil_scoped_release gil;
            return ImageProvider::create<VectorImageProvider>(std::string(source_url ? source_url : ""));
        }), arg("source_url") = nullptr, "doc")
        .def_property(
            "source_url", &VectorImageProvider::getSourceUrl,
            [](VectorImageProvider* self, const std::string& sourceUrl) { self->setSourceUrl(sourceUrl.c_str()); },
            "Sets the vector image URL. Asset loading doesn't happen immediately, but rather is started the next time widget is visible, in prepareDraw call.")
        .def_property("max_mip_levels", &VectorImageProvider::getMaxMipLevels, &VectorImageProvider::setMaxMipLevels,
                      "Maximum number of mip map levels allowed");
    /**/;
}
