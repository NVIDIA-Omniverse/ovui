/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_ValueModelHelper                                                                             \
    "The ValueModelHelper class provides the basic functionality for value widget classes.\n"                          \
    "ValueModelHelper class is the base class for every standard widget that uses a AbstractValueModel. ValueModelHelper is an abstract class and itself cannot be instantiated. It provides a standard interface for interoperating with models.\n"


#define OMNIUI_PYBIND_DOC_ValueModelHelper_onModelUpdated                                                              \
    "Called by the model when the model value is changed. The class should react to the changes.\n"


#define OMNIUI_PYBIND_DOC_ValueModelHelper_setModel "Set the current model.\n"


#define OMNIUI_PYBIND_DOC_ValueModelHelper_getModel "Returns the current model.\n"
