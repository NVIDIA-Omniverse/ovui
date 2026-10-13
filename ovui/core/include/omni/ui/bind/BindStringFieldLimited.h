/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindStringField.h"
#include "DocStringFieldLimited.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_StringFieldLimited                                                                          \
    OMNIUI_PYBIND_INIT_StringField                                                                                     \
    OMNIUI_PYBIND_INIT_CAST(max_length, setMaxLength, uint32_t)                                                        \
    OMNIUI_PYBIND_INIT_CALLBACK(character_limit_reached_fn, setCharacterLimitReachedFn, void(bool))

#define OMNIUI_PYBIND_KWARGS_DOC_StringFieldLimited                                                                    \
    "\n    `max_length : `\n        "                                                                                  \
    OMNIUI_PYBIND_DOC_StringFieldLimited_maxLength                                                                     \
    "\n    `character_limit_reached_fn : `\n        "                                                                  \
    OMNIUI_PYBIND_DOC_StringFieldLimited_CharacterLimitReached                                                         \
    OMNIUI_PYBIND_KWARGS_DOC_StringField
// clang-format on
