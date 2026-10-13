/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_StringFieldLimited                                                                           \
    "A StringField with an optional maximum character length.\n"                                                        \
    "\n"                                                                                                               \
    "Inherits every capability of StringField and adds a configurable character limit.\n"                              \
    "When the limit is reached, further input is blocked and an optional callback is invoked.\n"                       \
    "\n"


#define OMNIUI_PYBIND_DOC_StringFieldLimited_maxLength                                                                 \
    "This property holds the maximum number of characters allowed in the field.\n\n"                                   \
    "0 means no limit (uses ImGui's internal buffer limit).\n\n"                                                       \
    "When the limit is reached, further input is blocked and character_limit_reached_fn is invoked if set.\n"


#define OMNIUI_PYBIND_DOC_StringFieldLimited_CharacterLimitReached                                                     \
    "Callback when the 'at character limit' state changes.\n\n"                                                        \
    "Called with one bool argument (at_limit).\n"


#define OMNIUI_PYBIND_DOC_StringFieldLimited_StringFieldLimited                                                        \
    "Constructs StringFieldLimited.\n"                                                                                 \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `model :`\n"                                                                                                  \
    "        The widget's model. If the model is not assigned, the default model is created.\n"
