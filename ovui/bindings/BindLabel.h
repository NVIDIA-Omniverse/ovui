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

#include <omni/ui/Label.h>
#include <omni/ui/bind/BindLabel.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapLabel(module& m)
{
    constexpr const char* labelDoc = OMNIUI_PYBIND_CLASS_DOC(Label);
    static constexpr char labelConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Label, Label);

    class_<Label, Widget, std::shared_ptr<Label>>(m, "Label", labelDoc)
        .def(init([](std::string text, kwargs kwargs) { OMNIUI_PYBIND_INIT(Label, text) }), labelConstructorDoc)
        .def_property("text", &Label::getText, &Label::setText, OMNIUI_PYBIND_DOC_Label_text)
        .def_property("alignment", &Label::getAlignment, &Label::setAlignment, OMNIUI_PYBIND_DOC_Label_alignment)
        .def_property("word_wrap", &Label::isWordWrap, &Label::setWordWrap, OMNIUI_PYBIND_DOC_Label_wordWrap)
        .def_property("elided_text", &Label::isElidedText, &Label::setElidedText, OMNIUI_PYBIND_DOC_Label_elidedText)
        .def_property("elided_text_str", &Label::getElidedTextStr, &Label::setElidedTextStr, OMNIUI_PYBIND_DOC_Label_elidedTextStr)
        .def_property("hide_text_after_hash", &Label::isHideTextAfterHash, &Label::setHideTextAfterHash, OMNIUI_PYBIND_DOC_Label_hideTextAfterHash)
        .def_property_readonly("exact_content_width",
                               [](Label& self) { return self.exactContentWidth() / self.getDpiScale(); },
                               OMNIUI_PYBIND_DOC_Label_exactContentWidth)
        .def_property_readonly("exact_content_height",
                               [](Label& self) { return self.exactContentHeight() / self.getDpiScale(); },
                               OMNIUI_PYBIND_DOC_Label_exactContentHeight)
        /* */;
}
