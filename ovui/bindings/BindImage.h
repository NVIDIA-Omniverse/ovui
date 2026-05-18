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

#include <omni/ui/Image.h>
#include <omni/ui/bind/BindImage.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapImage(module& m)
{
    enum_<Image::FillPolicy>(m, "FillPolicy", "")
        .value("STRETCH", Image::FillPolicy::eStretch)
        .value("PRESERVE_ASPECT_FIT", Image::FillPolicy::ePreserveAspectFit)
        .value("PRESERVE_ASPECT_CROP", Image::FillPolicy::ePreserveAspectCrop);

    constexpr const char* imageDoc = OMNIUI_PYBIND_CLASS_DOC(Image);
    static constexpr char imageConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Image, Image);

    class_<Image, Widget, std::shared_ptr<Image>>(m, "Image", imageDoc)
        .def(init([](std::string sourceUrl, kwargs kwargs) { OMNIUI_PYBIND_INIT(Image, sourceUrl) }), imageConstructorDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(Image) }), imageConstructorDoc)
        .def_property("source_url", &Image::getSourceUrl, &Image::setSourceUrl, OMNIUI_PYBIND_DOC_Image_sourceUrl)
        .def_property("alignment", &Image::getAlignment, &Image::setAlignment, OMNIUI_PYBIND_DOC_Image_alignment)
        .def_property("fill_policy", &Image::getFillPolicy, &Image::setFillPolicy, OMNIUI_PYBIND_DOC_Image_fillPolicy)
        .def_property("pixel_aligned", &Image::getPixelAligned, &Image::setPixelAligned,
                      OMNIUI_PYBIND_DOC_Image_pixelAligned)
        .def_property_readonly("progress", &Image::getProgress, OMNIUI_PYBIND_DOC_Image_progress)
        .def("set_progress_changed_fn", wrapCallbackSetter(&Image::setProgressChangedFn), arg("fn"),
             OMNIUI_PYBIND_DOC_Image_progress)
        /* */;
}
