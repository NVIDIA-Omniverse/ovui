/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/scene/Label.h>
#include <omni/ui/scene/ShapeGesture.h>
#include <omni/ui/scene/bind/BindClickGesture.h>
#include <omni/ui/scene/bind/BindDoubleClickGesture.h>
#include <omni/ui/scene/bind/BindDragGesture.h>
#include <omni/ui/scene/bind/BindLabel.h>
#include <omni/ui/scene/bind/BindMath.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapLabel(module& m)
{
    constexpr const char* labelDoc = OMNIUI_PYBIND_CLASS_DOC(Label);
    static constexpr char labelConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Label, Label);

    class_<Label, AbstractShape, std::shared_ptr<Label>>(m, "Label", labelDoc)
        .def(init([](std::string text, kwargs kwargs) { OMNIUI_PYBIND_INIT(Label, text) }), labelConstructorDoc)
        .def_property("text", &Label::getText, &Label::setText, OMNIUI_PYBIND_DOC_Label_text)
        .def_property("alignment", &Label::getAlignment, &Label::setAlignment, OMNIUI_PYBIND_DOC_Label_alignment)
        .def_property("size", &Label::getSize, &Label::setSize, OMNIUI_PYBIND_DOC_Label_size)
        .def_property("color", [](const Label& self) { return vector4ToPython(self.getColor()); },
                      [](Label& self, const pybind11::handle& obj) { self.setColor(pythonToColor4(obj)); },
                      OMNIUI_PYBIND_DOC_Label_color)
        /* */;
}
