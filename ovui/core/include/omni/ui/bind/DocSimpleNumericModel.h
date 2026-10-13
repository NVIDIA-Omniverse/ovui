/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_SimpleNumericModel                                                                              \
    "A very simple value model that holds a single number. It's still an abstract class. It's necessary to reimplement\n" \
    "setValue(std::string value)\n"                                                                                       \
    "\n"


#define OMNIUI_PYBIND_DOC_SimpleNumericModel_min "This property holds the model's minimum value.\n"


#define OMNIUI_PYBIND_DOC_SimpleNumericModel_max "This property holds the model's maximum value.\n"


#define OMNIUI_PYBIND_DOC_SimpleNumericModel_getValueAsBool "Get the value as bool.\n"


#define OMNIUI_PYBIND_DOC_SimpleNumericModel_getValueAsFloat "Get the value as double.\n"


#define OMNIUI_PYBIND_DOC_SimpleNumericModel_getValueAsInt "Get the value as int64_t.\n"


#define OMNIUI_PYBIND_DOC_SimpleNumericModel_getValueAsString "Get the value as string.\n"


#define OMNIUI_PYBIND_DOC_SimpleNumericModel_setValue "Set the bool value. It will convert bool to the model's typle.\n"


#define OMNIUI_PYBIND_DOC_SimpleNumericModel_setValue01                                                                \
    "Set the double value. It will convert double to the model's typle.\n"


#define OMNIUI_PYBIND_DOC_SimpleNumericModel_setValue2                                                                 \
    "Set the int64_t value. It will convert int64_t to the model's typle.\n"
