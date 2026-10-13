/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "DocAbstractItem.h"

// clang-format off

#define OMNIUI_PYBIND_INIT_AbstractItem OMNIUI_PYBIND_INIT_CAST(visible, setVisible, bool)

#define OMNIUI_PYBIND_KWARGS_DOC_AbstractItem                                  \
    "\n    `visible : `\n        "                                             \
    OMNIUI_PYBIND_DOC_AbstractItem_visible

// clang-format on
