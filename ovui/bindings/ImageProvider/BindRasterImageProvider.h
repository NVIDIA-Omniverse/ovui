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

#include <omni/ui/ImageProvider/RasterImageProvider.h>
#include <omni/ui/bind/BindUtils.h>

#include <memory>
#include <string>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

// Sigh: pybind doesn't have a way to override destructors, so we must provide a deleter to the shared_ptr.
template<class T> void deleteWithoutGil(T* p)
{
    gil_scoped_release g;
    delete p;
}

void wrapRasterImageProvider(module& m)
{
    class_<RasterImageProvider, ImageProvider, std::shared_ptr<RasterImageProvider>>(m, "RasterImageProvider", "doc")
        .def(init([](const char* source_url, kwargs kwargs) {
                std::shared_ptr<RasterImageProvider> result;
                {
                    pybind11::gil_scoped_release gil;
                    result = ImageProvider::createWithDeleter<RasterImageProvider>(deleteWithoutGil<RasterImageProvider>,
                                                                                   std::string(source_url ? source_url : ""));
                }
                if (result)
                {
                    OMNIUI_PYBIND_INIT_BEGIN
                    // OMNIUI_PYBIND_INIT_RasterImageProvider
                    OMNIUI_PYBIND_INIT_END
                }
                return result;
        }), arg("source_url") = nullptr, "doc")
        .def_property(
            "source_url", &RasterImageProvider::getSourceUrl,
            [](RasterImageProvider* self, const std::string& sourceUrl) { self->setSourceUrl(sourceUrl.c_str()); },
            "Sets byte data that the image provider will turn into an image.")
        .def_property("max_mip_levels", &RasterImageProvider::getMaxMipLevels, &RasterImageProvider::setMaxMipLevels,
                      "Maximum number of mip map levels allowed");
    /**/;
}
