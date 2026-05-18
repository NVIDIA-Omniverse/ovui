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

#include <omni/ui/ImageWithProvider.h>
#include <omni/ui/bind/BindImageWithProvider.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_PROTECT_PYBIND11_OBJECT(OMNIUI_NS::ImageProvider, ImageProvider);

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapImageWithProvider(module& m)
{
    enum_<ImageWithProvider::FillPolicy>(m, "IwpFillPolicy", "")
        .value("IWP_STRETCH", ImageWithProvider::FillPolicy::eStretch)
        .value("IWP_PRESERVE_ASPECT_FIT", ImageWithProvider::FillPolicy::ePreserveAspectFit)
        .value("IWP_PRESERVE_ASPECT_CROP", ImageWithProvider::FillPolicy::ePreserveAspectCrop);

    constexpr const char* imageDoc = OMNIUI_PYBIND_CLASS_DOC(ImageWithProvider);
    static constexpr char imageConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(ImageWithProvider, ImageWithProvider);

    class_<ImageWithProvider, Widget, std::shared_ptr<ImageWithProvider>>(m, "ImageWithProvider", imageDoc)
        .def(init([](std::shared_ptr<ImageProvider> imageProvider, kwargs kwargs) {
            OMNIUI_PYBIND_INIT(ImageWithProvider, imageProvider)
        }))
        .def(init([](std::string url, kwargs kwargs) { OMNIUI_PYBIND_INIT(ImageWithProvider, url) }))
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(ImageWithProvider) }), imageConstructorDoc)
        .def("prepare_draw", &ImageWithProvider::prepareDraw, arg("width"), arg("height"),
             call_guard<gil_scoped_release>(), OMNIUI_PYBIND_DOC_ImageWithProvider_prepareDraw)
        .def_property("alignment", &ImageWithProvider::getAlignment, &ImageWithProvider::setAlignment,
                      OMNIUI_PYBIND_DOC_ImageWithProvider_alignment)
        .def_property("fill_policy", &ImageWithProvider::getFillPolicy, &ImageWithProvider::setFillPolicy,
                      OMNIUI_PYBIND_DOC_ImageWithProvider_fillPolicy)
        .def_property("pixel_aligned", &ImageWithProvider::getPixelAligned, &ImageWithProvider::setPixelAligned,
                      OMNIUI_PYBIND_DOC_ImageWithProvider_pixelAligned)
        /**/;
}
