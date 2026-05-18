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

#include "BindToolButton.h"
#include "BindUtils.h"

#include <omni/ui/RadioCollection.h>

// clang-format off
#define OMNIUI_PYBIND_INIT_RadioButton                                                                                 \
    OMNIUI_PYBIND_INIT_ToolButton                                                                                      \
    OMNIUI_PYBIND_INIT_CAST(radio_collection, setRadioCollection, std::shared_ptr<RadioCollection>)

#define OMNIUI_PYBIND_KWARGS_DOC_RadioButton                                                                           \
    "\n    `radio_collection : `\n        "                                                                            \
    OMNIUI_PYBIND_DOC_RadioButton_radioCollection                                                                      \
    OMNIUI_PYBIND_KWARGS_DOC_Button
// clang-format on
