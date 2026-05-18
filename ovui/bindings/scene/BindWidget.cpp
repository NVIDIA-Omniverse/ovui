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

#include <omni/ui/Frame.h>
#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/scene/ShapeGesture.h>
#include <omni/ui/scene/Widget.h>
#include <omni/ui/scene/bind/BindClickGesture.h>
#include <omni/ui/scene/bind/BindDoubleClickGesture.h>
#include <omni/ui/scene/bind/BindDragGesture.h>
#include <omni/ui/scene/bind/BindMath.h>
#include <omni/ui/scene/bind/BindWidget.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapWidget(module& m)
{
    using Widget = omni::ui::scene::Widget;

    constexpr const char* widgetDoc = OMNIUI_PYBIND_CLASS_DOC(Widget);
    static constexpr char widgetConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Widget, Widget);

    auto widget = class_<Widget, Rectangle, std::shared_ptr<Widget>>(m, "Widget", widgetDoc);

    enum_<Widget::FillPolicy>(widget, "FillPolicy")
        .value("STRETCH", Widget::FillPolicy::eStretch)
        .value("PRESERVE_ASPECT_FIT", Widget::FillPolicy::ePreserveAspectFit)
        .value("PRESERVE_ASPECT_CROP", Widget::FillPolicy::ePreserveAspectCrop);

    enum_<Widget::UpdatePolicy>(widget, "UpdatePolicy")
        .value("ON_DEMAND", Widget::UpdatePolicy::eOnDemand)
        .value("ALWAYS", Widget::UpdatePolicy::eAlways)
        .value("ON_MOUSE_HOVERED", Widget::UpdatePolicy::eOnMouseHovered);

    widget
        .def(init([](Float width, Float height, kwargs kwargs) { OMNIUI_PYBIND_INIT(Widget, width, height) }),
             arg("width"), arg("height"), widgetConstructorDoc)
        .def("invalidate", &Widget::invalidate, OMNIUI_PYBIND_DOC_Widget_invalidate)
        .def_property_readonly("frame", &Widget::getFrame, OMNIUI_PYBIND_DOC_Widget_getFrame)
        .def_property("fill_policy", &Widget::getFillPolicy, &Widget::setFillPolicy, OMNIUI_PYBIND_DOC_Widget_fillPolicy)
        .def_property(
            "update_policy", &Widget::getUpdatePolicy, &Widget::setUpdatePolicy, OMNIUI_PYBIND_DOC_Widget_updatePolicy)
        .def_property("resolution_scale", &Widget::getResolutionScale, &Widget::setResolutionScale,
                      OMNIUI_PYBIND_DOC_Widget_resolutionScale)
        .def_property("resolution_width", &Widget::getResolutionWidth, &Widget::setResolutionWidth,
                      OMNIUI_PYBIND_DOC_Widget_resolutionWidth)
        .def_property("resolution_height", &Widget::getResolutionHeight, &Widget::setResolutionHeight,
                      OMNIUI_PYBIND_DOC_Widget_resolutionHeight)

        /* */;
}
