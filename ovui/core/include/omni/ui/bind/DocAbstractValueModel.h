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

#define OMNIUI_PYBIND_DOC_AbstractValueModel                                                                           \
    "\n"                                                                                                               \
    "\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_getValueAsBool "Return the bool representation of the value.\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_getValueAsFloat "Return the float representation of the value.\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_getValueAsInt "Return the int representation of the value.\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_getValueAsString "Return the string representation of the value.\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_getValue "A helper that calls the correct getValueXXX method.\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_beginEdit                                                                 \
    "Called when the user starts the editing. If it's a field, this method is called when the user activates the field and places the cursor inside. This method should be reimplemented.\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_endEdit                                                                   \
    "Called when the user finishes the editing. If it's a field, this method is called when the user presses Enter or selects another field for editing. It's useful for undo/redo. This method should be reimplemented.\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_setValue "Set the value.\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_subscribe                                                                 \
    "Subscribe the ValueModelHelper widget to the changes of the model.\n"                                             \
    "We need to use regular pointers because we subscribe in the constructor of the widget and unsubscribe in the destructor. In constructor smart pointers are not available. We also don't allow copy and move of the widget.\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_unsubscribe                                                               \
    "Unsubscribe the ValueModelHelper widget from the changes of the model.\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_addValueChangedFn                                                         \
    "Adds the function that will be called every time the value changes.\n"                                            \
    "The id of the callback that is used to remove the callback.\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_removeValueChangedFn                                                      \
    "Remove the callback by its id.\n"                                                                                 \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `id :`\n"                                                                                                     \
    "        The id that addValueChangedFn returns.\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_addBeginEditFn                                                            \
    "Adds the function that will be called every time the user starts the editing.\n"                                  \
    "The id of the callback that is used to remove the callback.\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_removeBeginEditFn                                                         \
    "Remove the callback by its id.\n"                                                                                 \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `id :`\n"                                                                                                     \
    "        The id that addBeginEditFn returns.\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_addEndEditFn                                                              \
    "Adds the function that will be called every time the user finishes the editing.\n"                                \
    "The id of the callback that is used to remove the callback.\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_removeEndEditFn                                                           \
    "Remove the callback by its id.\n"                                                                                 \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `id :`\n"                                                                                                     \
    "        The id that addEndEditFn returns.\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_processBeginEditCallbacks                                                 \
    "Called by the widget when the user starts editing. It calls beginEdit and the callbacks.\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_processEndEditCallbacks                                                   \
    "Called by the widget when the user finishes editing. It calls endEdit and the callbacks.\n"


#define OMNIUI_PYBIND_DOC_AbstractValueModel_AbstractValueModel "Constructs AbstractValueModel.\n"
