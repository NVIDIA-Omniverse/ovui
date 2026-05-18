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

#define OMNIUI_PYBIND_DOC_AbstractField                                                                                \
    "The abstract widget that is base for any field, which is a one-line text editor.\n"                               \
    "A field allows the user to enter and edit a single line of plain text. It's implemented using the model-view pattern and uses AbstractValueModel as the central component of the system.\n"


#define OMNIUI_PYBIND_DOC_AbstractField_setComputedContentWidth                                                        \
    "Reimplemented the method to indicate the width hint that represents the preferred size of the widget.\n"


#define OMNIUI_PYBIND_DOC_AbstractField_setComputedContentHeight                                                       \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget.\n"


#define OMNIUI_PYBIND_DOC_AbstractField_onStyleUpdated                                                                 \
    "Reimplemented. Something happened with the style or with the parent style. We need to gerenerate the cache.\n"


#define OMNIUI_PYBIND_DOC_AbstractField_onModelUpdated                                                                 \
    "Reimplemented the method from ValueModelHelper that is called when the model is changed.\n"


#define OMNIUI_PYBIND_DOC_AbstractField_focusKeyboard                                                                  \
    "Puts cursor to this field or removes focus if\n"                                                                  \
    "focus\n"


#define OMNIUI_PYBIND_DOC_AbstractField__onInputTextActive                                                             \
    "Internal private callback. It's called when the internal text buffer needs to change the size.\n"
