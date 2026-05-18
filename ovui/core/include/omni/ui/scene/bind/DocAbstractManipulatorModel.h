/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#define OMNIUI_PYBIND_DOC_AbstractManipulatorModel                                                                     \
    "\n"                                                                                                               \
    "Bridge to data.\n"                                                                                                \
    "Operates with double and int arrays.\n"                                                                           \
    "No strings.\n"                                                                                                    \
    "No tree, it's a flat list of items.\n"                                                                            \
    "Manipulator requires the model has specific items.\n"


#define OMNIUI_PYBIND_DOC_AbstractManipulatorModel_getItem "Returns the items that represents the identifier.\n"


#define OMNIUI_PYBIND_DOC_AbstractManipulatorModel_getAsFloats "Returns the Float values of the item.\n"


#define OMNIUI_PYBIND_DOC_AbstractManipulatorModel_getAsInts "Returns the int values of the item.\n"


#define OMNIUI_PYBIND_DOC_AbstractManipulatorModel_setFloats "Sets the Float values of the item.\n"


#define OMNIUI_PYBIND_DOC_AbstractManipulatorModel_setInts "Sets the int values of the item.\n"


#define OMNIUI_PYBIND_DOC_AbstractManipulatorModel_subscribe                                                           \
    "Subscribe ManipulatorModelHelper to the changes of the model.\n"                                                  \
    "We need to use regular pointers because we subscribe in the constructor of the widget and unsubscribe in the destructor. In constructor smart pointers are not available. We also don't allow copy and move of the widget.\n"


#define OMNIUI_PYBIND_DOC_AbstractManipulatorModel_unsubscribe                                                         \
    "Unsubscribe the ItemModelHelper widget from the changes of the model.\n"


#define OMNIUI_PYBIND_DOC_AbstractManipulatorModel_addItemChangedFn                                                    \
    "Adds the function that will be called every time the value changes.\n"                                            \
    "The id of the callback that is used to remove the callback.\n"


#define OMNIUI_PYBIND_DOC_AbstractManipulatorModel_removeItemChangedFn                                                 \
    "Remove the callback by its id.\n"                                                                                 \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `id :`\n"                                                                                                     \
    "        The id that addValueChangedFn returns.\n"
