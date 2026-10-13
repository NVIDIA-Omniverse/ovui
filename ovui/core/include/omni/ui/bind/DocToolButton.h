/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_ToolButton                                                                                                                                                                       \
    "ToolButton is functionally similar to Button, but provides a model that determines if the button is checked. This button toggles between checked (on) and unchecked (off) when the user clicks it.\n" \
    "\n"


#define OMNIUI_PYBIND_DOC_ToolButton_onModelUpdated                                                                    \
    "Reimplemented from ValueModelHelper. It's called when the model is changed.\n"


#define OMNIUI_PYBIND_DOC_ToolButton_ToolButton                                                                        \
    "Construct a checkable button with the model. If the bodel is not provided, then the default model is created.\n"  \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `model :`\n"                                                                                                  \
    "        The model that determines if the button is checked.\n"
