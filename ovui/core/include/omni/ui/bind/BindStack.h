/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindContainer.h"
#include "BindUtils.h"
#include "DocStack.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_Stack                                                                                       \
    OMNIUI_PYBIND_INIT_Container                                                                                       \
    OMNIUI_PYBIND_INIT_CAST(direction, setDirection, Stack::Direction)                                                 \
    OMNIUI_PYBIND_INIT_CAST(content_clipping, setContentClipping, bool)                                                \
    OMNIUI_PYBIND_INIT_CAST(spacing, setSpacing, float)                                                                \
    OMNIUI_PYBIND_INIT_CAST(send_mouse_events_to_back, setSendMouseEventsToBack, bool)

#define OMNIUI_PYBIND_KWARGS_DOC_Stack                                                                                 \
    "\n    `direction : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_Stack_Direction                                                                                  \
    "\n    `content_clipping : `\n        "                                                                            \
    OMNIUI_PYBIND_DOC_Stack_contentClipping                                                                            \
    "\n    `spacing : `\n        "                                                                                     \
    OMNIUI_PYBIND_DOC_Stack_spacing                                                                                    \
    "\n    `send_mouse_events_to_back : `\n        "                                                                   \
    OMNIUI_PYBIND_DOC_Stack_sendMouseEventsToBack                                                                      \
    OMNIUI_PYBIND_KWARGS_DOC_Container
// clang-format on
