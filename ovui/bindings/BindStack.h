/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include <omni/ui/Stack.h>
#include <omni/ui/bind/BindStack.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapStack(module& m)
{
    enum_<Stack::Direction>(m, "Direction", "")
        .value("LEFT_TO_RIGHT", Stack::Direction::eLeftToRight)
        .value("RIGHT_TO_LEFT", Stack::Direction::eRightToLeft)
        .value("TOP_TO_BOTTOM", Stack::Direction::eTopToBottom)
        .value("BOTTOM_TO_TOP", Stack::Direction::eBottomToTop)
        .value("BACK_TO_FRONT", Stack::Direction::eBackToFront)
        .value("FRONT_TO_BACK", Stack::Direction::eFrontToBack);

    constexpr const char* stackDoc = OMNIUI_PYBIND_CLASS_DOC(Stack);
    static constexpr char stackConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Stack, Stack);

    class_<Stack, Container, std::shared_ptr<Stack>>(m, "Stack", stackDoc)
        .def(init([](Stack::Direction direction, kwargs kwargs) { OMNIUI_PYBIND_INIT(Stack, direction) }),
             stackConstructorDoc)
        .def_property("direction", &Stack::getDirection, &Stack::setDirection, OMNIUI_PYBIND_DOC_Stack_Direction)
        .def_property("content_clipping", &Stack::isContentClipping, &Stack::setContentClipping,
                      OMNIUI_PYBIND_DOC_Stack_contentClipping)
        .def_property("spacing", &Stack::getSpacing, &Stack::setSpacing, OMNIUI_PYBIND_DOC_Stack_spacing)
        .def_property("send_mouse_events_to_back", &Stack::isSendMouseEventsToBack, &Stack::setSendMouseEventsToBack,
                      OMNIUI_PYBIND_DOC_Stack_sendMouseEventsToBack);
}
