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

#define OMNIUI_PYBIND_DOC_AbstractItemModel                                                                                                                                                                                                                                                                                                                                                                                                                          \
    "The central component of the item widget. It is the application's dynamic data structure, independent of the user interface, and it directly manages the nested data. It follows closely model-view pattern. It's abstract, and it defines the standard interface to be able to interoperate with the components of the model-view architecture. It is not supposed to be instantiated directly. Instead, the user should subclass it to create a new model.\n" \
    "The item model doesn't return the data itself. Instead, it returns the value model that can contain any data type and supports callbacks. Thus the client of the model can track the changes in both the item model and any value it holds.\n"                                                                                                                                                                                                                  \
    "From any item, the item model can get both the value model and the nested items. Therefore, the model is flexible to represent anything from color to complicated tree-table construction.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_getItemChildren                                                            \
    "Returns the vector of items that are nested to the given parent item.\n"                                          \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `id :`\n"                                                                                                     \
    "        The item to request children from. If it's null, the children of root will be returned.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_canItemHaveChildren                                                        \
    "Returns true if the item can have children. In this way the delegate usually draws +/- icon.\n"                   \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `id :`\n"                                                                                                     \
    "        The item to request children from. If it's null, the children of root will be returned.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_appendChildItem                                                            \
    "Creates a new item from the value model and appends it to the list of the children of the given item.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_removeItem                                                                 \
    "Removes the item from the model.\n"                                                                               \
    "There is no parent here because we assume that the reimplemented model deals with its data and can figure out how to remove this item.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_getItemValueModelCount                                                     \
    "Returns the number of columns this model item contains.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_getItemValueModel                                                          \
    "Get the value model associated with this item.\n"                                                                 \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `item :`\n"                                                                                                   \
    "        The item to request the value model from. If it's null, the root value model will be returned.\n"         \
    "\n"                                                                                                               \
    "    `index :`\n"                                                                                                  \
    "        The column number to get the value model.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_beginEdit                                                                  \
    "Called when the user starts the editing. If it's a field, this method is called when the user activates the field and places the cursor inside.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_endEdit                                                                    \
    "Called when the user finishes the editing. If it's a field, this method is called when the user presses Enter or selects another field for editing. It's useful for undo/redo.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_dropAccepted                                                               \
    "Called to determine if the model can perform drag and drop to the given item. If this method returns false, the widget shouldn't highlight the visual element that represents this item.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_dropAccepted01                                                             \
    "Called to determine if the model can perform drag and drop of the given string to the given item. If this method returns false, the widget shouldn't highlight the visual element that represents this item.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_drop                                                                                                                                                                            \
    "Called when the user droped one item to another.\n"                                                                                                                                                                    \
    "Small explanation why the same default value is declared in multiple places. We use the default value to be compatible with the previous API and especially with Stage 2.0. Thr signature in the old Python API is:\n" \
    "def drop(self, target_item, source)\n"                                                                                                                                                                                 \
    "drop(self, target_item, source)\n"                                                                                                                                                                                     \
    "PyAbstractItemModel::drop\n"                                                                                                                                                                                           \
    "AbstractItemModel.drop\n"                                                                                                                                                                                              \
    "pybind11::class_<AbstractItemModel>.def(\"drop\")\n"                                                                                                                                                                   \
    "AbstractItemModel\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_drop01 "Called when the user droped a string to the item.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_getDragMimeData                                                            \
    "Returns Multipurpose Internet Mail Extensions (MIME) for drag and drop.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_subscribe                                                                  \
    "Subscribe the ItemModelHelper widget to the changes of the model.\n"                                              \
    "We need to use regular pointers because we subscribe in the constructor of the widget and unsubscribe in the destructor. In constructor smart pointers are not available. We also don't allow copy and move of the widget.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_unsubscribe                                                                \
    "Unsubscribe the ItemModelHelper widget from the changes of the model.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_addItemChangedFn                                                           \
    "Adds the function that will be called every time the value changes.\n"                                            \
    "The id of the callback that is used to remove the callback.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_removeItemChangedFn                                                        \
    "Remove the callback by its id.\n"                                                                                 \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `id :`\n"                                                                                                     \
    "        The id that addValueChangedFn returns.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_addBeginEditFn                                                             \
    "Adds the function that will be called every time the user starts the editing.\n"                                  \
    "The id of the callback that is used to remove the callback.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_removeBeginEditFn                                                          \
    "Remove the callback by its id.\n"                                                                                 \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `id :`\n"                                                                                                     \
    "        The id that addBeginEditFn returns.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_addEndEditFn                                                               \
    "Adds the function that will be called every time the user finishes the editing.\n"                                \
    "The id of the callback that is used to remove the callback.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_removeEndEditFn                                                            \
    "Remove the callback by its id.\n"                                                                                 \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `id :`\n"                                                                                                     \
    "        The id that addEndEditFn returns.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_processBeginEditCallbacks                                                  \
    "Called by the widget when the user starts editing. It calls beginEdit and the callbacks.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_processEndEditCallbacks                                                    \
    "Called by the widget when the user finishes editing. It calls endEdit and the callbacks.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemModel_AbstractItemModel "Constructs AbstractItemModel.\n"
