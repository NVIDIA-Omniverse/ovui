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

#include <omni/ui/Button.h>
#include <omni/ui/bind/BindButton.h>
#include <omni/ui/bind/BindUtils.h>

#include <memory>
#include <string>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapButton(module& m)
{
    constexpr const char* buttonDoc = OMNIUI_PYBIND_CLASS_DOC(Button);
    static constexpr char buttonConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Button, Button);

    class_<Button, InvisibleButton, std::shared_ptr<Button>>(m, "Button", buttonDoc)
        .def(init([](std::string text, kwargs kwargs) { OMNIUI_PYBIND_INIT(Button, text) }), arg("text") = "",
             buttonConstructorDoc)
        .def_property("text", &Button::getText, &Button::setText, OMNIUI_PYBIND_DOC_Button_text)
        .def_property("image_url", &Button::getImageUrl, &Button::setImageUrl, OMNIUI_PYBIND_DOC_Button_imageUrl)
        .def_property("image_width", &Button::getImageWidth, &Button::setImageWidth, OMNIUI_PYBIND_DOC_Button_imageWidth)
        .def_property(
            "image_height", &Button::getImageHeight, &Button::setImageHeight, OMNIUI_PYBIND_DOC_Button_imageHeight)
        .def_property("spacing", &Button::getSpacing, &Button::setSpacing, OMNIUI_PYBIND_DOC_Button_spacing);
}
