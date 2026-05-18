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

#include <omni/ui/Widget.h>
#include <omni/ui/bind/BindStyleContainer.h>
#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/bind/BindWidget.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapWidget(module& m)
{
    static constexpr char widgetMouseDropEventDoc[] = "Holds the data which is sent when a drag and drop action is completed.";
    static constexpr char widgetMouseDropEventPositionDoc[] = "Position where the drop was made.";
    static constexpr char widgetMouseDropEventDataDoc[] = "The data that was dropped on the widget.";

    // Widget::kModifierFlagWantCaptureKeyboard is constexpr, but we need a pointer to it.
    static uint32_t kModifierFlagWantCaptureKeyboard = Widget::kModifierFlagWantCaptureKeyboard;

    class_<Widget::MouseDropEvent, std::shared_ptr<Widget::MouseDropEvent>>(
        m, "WidgetMouseDropEvent", widgetMouseDropEventDoc)
        .def_property_readonly(
            "x", [](const Widget::MouseDropEvent& self) { return self.x; }, widgetMouseDropEventPositionDoc)
        .def_property_readonly(
            "y", [](const Widget::MouseDropEvent& self) { return self.y; }, widgetMouseDropEventPositionDoc)
        .def_property_readonly(
            "mime_data", [](const Widget::MouseDropEvent& self) { return self.mimeData; }, widgetMouseDropEventDataDoc)
        .def("__str__", [](const Widget::MouseDropEvent& self) { return self.mimeData; })
        .def("__repr__", [](const Widget::MouseDropEvent& self) { return self.mimeData; });

    constexpr const char* widgetDoc = OMNIUI_PYBIND_CLASS_DOC(Widget);

    class_<Widget, std::shared_ptr<Widget>>(m, "Widget", widgetDoc)
        .def_readonly_static("FLAG_WANT_CAPTURE_KEYBOARD", &kModifierFlagWantCaptureKeyboard,
                             OMNIUI_PYBIND_DOC_Widget_kModifierFlagWantCaptureKeyboard)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(Widget) }), "")
        .def("destroy", &Widget::destroy, OMNIUI_PYBIND_DOC_Widget_destroy)
        .def("set_style", [](Widget& self, const pybind11::handle& style) { setWidgetStyle(self, style); },
             OMNIUI_PYBIND_DOC_Widget_setStyle)
        .def_property("width", &Widget::getWidth, &Widget::setWidth, OMNIUI_PYBIND_DOC_Widget_width)
        .def_property("height", &Widget::getHeight, &Widget::setHeight, OMNIUI_PYBIND_DOC_Widget_height)
        .def_property("name", &Widget::getName, &Widget::setName, OMNIUI_PYBIND_DOC_Widget_name)
        .def_property("style_type_name_override", &Widget::getStyleTypeNameOverride, &Widget::setStyleTypeNameOverride,
                      OMNIUI_PYBIND_DOC_Widget_styleTypeNameOverride)
        .def_property("identifier", &Widget::getIdentifier, &Widget::setIdentifier,
                      OMNIUI_PYBIND_DOC_Widget_identifier)
        .def_property("style", &getPythonStyle, &setWidgetStyle, OMNIUI_PYBIND_DOC_Widget_style)
        .def_property("visible", &Widget::isVisible, &Widget::setVisible, OMNIUI_PYBIND_DOC_Widget_visible)
        .def_property("visible_min", &Widget::getVisibleMin, &Widget::setVisibleMin, OMNIUI_PYBIND_DOC_Widget_visibleMin)
        .def_property("visible_max", &Widget::getVisibleMax, &Widget::setVisibleMax, OMNIUI_PYBIND_DOC_Widget_visibleMax)
        .def_property("tooltip", &Widget::getTooltip, &Widget::setTooltip, OMNIUI_PYBIND_DOC_Widget_tooltip)
        .def("set_tooltip", &Widget::setTooltip, arg("tooltip_label"), OMNIUI_PYBIND_DOC_Widget_tooltip)
        .def("scroll_here_x", &Widget::scrollHereX, arg("center_ratio") = 0.f, OMNIUI_PYBIND_DOC_Widget_scrollHereX)
        .def("scroll_here_y", &Widget::scrollHereY, arg("center_ratio") = 0.f, OMNIUI_PYBIND_DOC_Widget_scrollHereY)
        .def("scroll_here", &Widget::scrollHere, arg("center_ratio_x") = 0.f, arg("center_ratio_y") = 0.f,
             OMNIUI_PYBIND_DOC_Widget_scrollHere)
        .def_property("tooltip_offset_x", &Widget::getTooltipOffsetX, &Widget::setTooltipOffsetX,
                      OMNIUI_PYBIND_DOC_Widget_tooltipOffsetX)
        .def_property("tooltip_offset_y", &Widget::getTooltipOffsetY, &Widget::setTooltipOffsetY,
                      OMNIUI_PYBIND_DOC_Widget_tooltipOffsetY)
        .def_property("enabled", &Widget::isEnabled, &Widget::setEnabled, OMNIUI_PYBIND_DOC_Widget_enabled)
        .def_property("selected", &Widget::isSelected, &Widget::setSelected, OMNIUI_PYBIND_DOC_Widget_selected)
        .def_property("checked", &Widget::isChecked, &Widget::setChecked, OMNIUI_PYBIND_DOC_Widget_checked)
        .def_property("dragging", &Widget::isDragging, &Widget::setDragging, OMNIUI_PYBIND_DOC_Widget_dragging)
        .def_property("opaque_for_mouse_events", &Widget::isOpaqueForMouseEvents, &Widget::setOpaqueForMouseEvents,
                      OMNIUI_PYBIND_DOC_Widget_opaqueForMouseEvents)
        .def_property("explicit_hover", &Widget::isExplicitHover, &Widget::setExplicitHover,
                      OMNIUI_PYBIND_DOC_Widget_explicitHover)
        .def_property("skip_draw_when_clipped", &Widget::isSkipDrawWhenClipped, &Widget::setSkipDrawWhenClipped,
                      OMNIUI_PYBIND_DOC_Widget_skipDrawWhenClipped)
        .def_property("scroll_only_window_hovered", &Widget::isScrollOnlyWindowHovered,
                      &Widget::setScrollOnlyWindowHovered, OMNIUI_PYBIND_DOC_Widget_scrollOnlyWindowHovered)
        .def_property_readonly("computed_width",
                               [](Widget& self) { return self.getComputedWidth() / self.getDpiScale(); },
                               OMNIUI_PYBIND_DOC_Widget_getComputedWidth)
        .def_property_readonly("computed_height",
                               [](Widget& self) { return self.getComputedHeight() / self.getDpiScale(); },
                               OMNIUI_PYBIND_DOC_Widget_getComputedHeight)
        .def_property_readonly("computed_content_width",
                               [](Widget& self) { return self.getComputedContentWidth() / self.getDpiScale(); },
                               OMNIUI_PYBIND_DOC_Widget_getComputedContentWidth)
        .def_property_readonly("computed_content_height",
                               [](Widget& self) { return self.getComputedContentHeight() / self.getDpiScale(); },
                               OMNIUI_PYBIND_DOC_Widget_getComputedContentHeight)
        .def_property_readonly("screen_position_x",
                               [](Widget& self) { return self.getScreenPositionX() / self.getDpiScale(); },
                               OMNIUI_PYBIND_DOC_Widget_getScreenPositionX)
        .def_property_readonly("screen_position_y",
                               [](Widget& self) { return self.getScreenPositionY() / self.getDpiScale(); },
                               OMNIUI_PYBIND_DOC_Widget_getScreenPositionY)
        .def("set_checked_changed_fn", wrapCallbackSetter(&Widget::setCheckedChangedFn), arg("fn"),
             OMNIUI_PYBIND_DOC_Widget_checked)
        .OMNIUI_PYBIND_DEF_CALLBACK(tooltip, Widget, Tooltip)
        .OMNIUI_PYBIND_DEF_CALLBACK(mouse_moved, Widget, MouseMoved)
        .OMNIUI_PYBIND_DEF_CALLBACK(mouse_pressed, Widget, MousePressed)
        .OMNIUI_PYBIND_DEF_CALLBACK(mouse_released, Widget, MouseReleased)
        .OMNIUI_PYBIND_DEF_CALLBACK(mouse_double_clicked, Widget, MouseDoubleClicked)
        .OMNIUI_PYBIND_DEF_CALLBACK(mouse_wheel, Widget, MouseWheel)
        .OMNIUI_PYBIND_DEF_CALLBACK(mouse_hovered, Widget, MouseHovered)
        .OMNIUI_PYBIND_DEF_CALLBACK(key_pressed, Widget, KeyPressed)
        .OMNIUI_PYBIND_DEF_CALLBACK(drag, Widget, Drag)
        .OMNIUI_PYBIND_DEF_CALLBACK(accept_drop, Widget, AcceptDrop)
        .OMNIUI_PYBIND_DEF_CALLBACK(drop, Widget, Drop)
        .OMNIUI_PYBIND_DEF_CALLBACK(computed_content_size_changed, Widget, ComputedContentSizeChanged)
        /**/;
}
