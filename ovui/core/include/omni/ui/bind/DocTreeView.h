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

#define OMNIUI_PYBIND_DOC_TreeView                                                                                                                                                                                                                                                                                                 \
    "TreeView is a widget that presents a hierarchical view of information. Each item can have a number of subitems. An indentation often visualizes this in a list. An item can be expanded to reveal subitems, if any exist, and collapsed to hide subitems.\n"                                                                     \
    "TreeView can be used in file manager applications, where it allows the user to navigate the file system directories. They are also used to present hierarchical data, such as the scene object hierarchy.\n"                                                                                                                  \
    "TreeView uses a model/view pattern to manage the relationship between data and the way it is presented. The separation of functionality gives developers greater flexibility to customize the presentation of items and provides a standard interface to allow a wide range of data sources to be used with other widgets.\n" \
    "TreeView is responsible for the presentation of model data to the user and processing user input. To allow some flexibility in the way the data is presented, the creation of the sub-widgets is performed by the delegate. It provides the ability to customize any sub-item of TreeView.\n"


#define OMNIUI_PYBIND_DOC_TreeView_DropLocation                                                                        \
    "The location of Drag and Drop.\n"                                                                                 \
    "Specifies where exactly the user droped the item.\n"


#define OMNIUI_PYBIND_DOC_TreeView_setComputedContentWidth                                                             \
    "Reimplemented the method to indicate the width hint that represents the preferred size of the widget.\n"


#define OMNIUI_PYBIND_DOC_TreeView_setComputedContentHeight                                                            \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget.\n"


#define OMNIUI_PYBIND_DOC_TreeView_onModelUpdated                                                                      \
    "Reimplemented the method from ItemModelHelper that is called when the model is changed.\n"                        \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `item :`\n"                                                                                                   \
    "        The item in the model that is changed. If it's NULL, the root is chaged.\n"


#define OMNIUI_PYBIND_DOC_TreeView_clearSelection "Deselects all selected items.\n"


#define OMNIUI_PYBIND_DOC_TreeView_setSelection "Set current selection.\n"


#define OMNIUI_PYBIND_DOC_TreeView_toggleSelection "Switches the selection state of the given item.\n"


#define OMNIUI_PYBIND_DOC_TreeView_extendSelection                                                                     \
    "Extends the current selection selecting all the items between currently selected nodes and the given item. It's when user does shift+click.\n"


#define OMNIUI_PYBIND_DOC_TreeView_getSelection "Return the list of selected items.\n"


#define OMNIUI_PYBIND_DOC_TreeView_SelectionChanged "Set the callback that is called when the selection is changed.\n"


#define OMNIUI_PYBIND_DOC_TreeView_HoverChanged "Set the callback that is called when the item hover status is changed.\n"


#define OMNIUI_PYBIND_DOC_TreeView_isExpanded "Returns true if the given item is expanded.\n"


#define OMNIUI_PYBIND_DOC_TreeView_setExpanded                                                                         \
    "Sets the given item expanded or collapsed.\n"                                                                     \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `item :`\n"                                                                                                   \
    "        The item to expand or collapse.\n"                                                                        \
    "\n"                                                                                                               \
    "    `expanded :`\n"                                                                                               \
    "        True if it's necessary to expand, false to collapse.\n"                                                   \
    "\n"                                                                                                               \
    "    `recursive :`\n"                                                                                              \
    "        True if it's necessary to expand children.\n"


#define OMNIUI_PYBIND_DOC_TreeView_dirtyWidgets                                                                        \
    "When called, it will make the delegate to regenerate all visible widgets the next frame.\n"


#define OMNIUI_PYBIND_DOC_TreeView_delegate "The Item delegate that generates a widget per item.\n"


#define OMNIUI_PYBIND_DOC_TreeView_columnWidths "Widths of the columns. If not set, the width is Fraction(1).\n"


#define OMNIUI_PYBIND_DOC_TreeView_minColumnWidths "Minimum widths of the columns. If not set, the width is Pixel(0).\n"


#define OMNIUI_PYBIND_DOC_TreeView_columnsResizable "When true, the columns can be resized with the mouse.\n"


#define OMNIUI_PYBIND_DOC_TreeView_resizableOnColumnsResized                                                          \
    "When true, the treeview is resizable when columns are resized. Otherwise, treeview width is fixed when columns are resized.\n"


#define OMNIUI_PYBIND_DOC_TreeView_fixedWidthColumns                                                             \
    "This property holds the list of whether a column can be resized or not.\n"


#define OMNIUI_PYBIND_DOC_TreeView_headerVisible "This property holds if the header is shown or not.\n"


#define OMNIUI_PYBIND_DOC_TreeView_rootVisible                                                                         \
    "This property holds if the root is shown. It can be used to make a single level tree appear like a simple list.\n"


#define OMNIUI_PYBIND_DOC_TreeView_expandOnBranchClick                                                                 \
    "This flag allows to prevent expanding when the user clicks the plus icon. It's used in the case the user wants to control how the items expanded or collapsed.\n"


#define OMNIUI_PYBIND_DOC_TreeView_autoScrollSelection                                                                 \
    "When true, a single selected item is automatically scrolled into view.\n"


#define OMNIUI_PYBIND_DOC_TreeView_keepAlive                                                                           \
    "When true, the tree nodes are never destroyed even if they are disappeared from the model. It's useul for the temporary filtering if it's necessary to display thousands of nodes.\n"


#define OMNIUI_PYBIND_DOC_TreeView_keepExpanded "Expand all the nodes and keep them expanded regardless their state.\n"


#define OMNIUI_PYBIND_DOC_TreeView_dropBetweenItems "When true, the tree nodes can be dropped between items.\n"


#define OMNIUI_PYBIND_DOC_TreeView_rootExpanded                                                                        \
    "The expanded state of the root item. Changing this flag doesn't make the children repopulated.\n"


#define OMNIUI_PYBIND_DOC_TreeView_TreeView                                                                            \
    "Create TreeView with the given model.\n"                                                                          \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `model :`\n"                                                                                                  \
    "        The given model.\n"


#define OMNIUI_PYBIND_DOC_TreeView__clearNodeSelection "Deselects the given node and the children.\n"


#define OMNIUI_PYBIND_DOC_TreeView__getDropNode                                                                                                                         \
    "This function converts the flat drop location (above-below-over) on the table to the tree's location.\n"                                                           \
    "When the user drops an item, he drops it between rows. And we need to know the child index that corresponds to the parent into which the new rows are inserted.\n" \
    "\n"                                                                                                                                                                \
    "\n"                                                                                                                                                                \
    "### Arguments:\n"                                                                                                                                                  \
    "\n"                                                                                                                                                                \
    "    `node :`\n"                                                                                                                                                    \
    "        The node the user droped something.\n"                                                                                                                     \
    "\n"                                                                                                                                                                \
    "    `parent :`\n"                                                                                                                                                  \
    "        The parent of the node the user droped it.\n"                                                                                                              \
    "\n"                                                                                                                                                                \
    "    `dropLocation :`\n"                                                                                                                                            \
    "        Above-below-over position in the table.\n"                                                                                                                 \
    "\n"                                                                                                                                                                \
    "    `dropNode :`\n"                                                                                                                                                \
    "        Output. The parent node into which the new item should be inserted.\n"                                                                                     \
    "\n"                                                                                                                                                                \
    "    `dropId :`\n"                                                                                                                                                  \
    "        Output. The index of child the new item should be inserted. If -1, the new item should be inseted to the end.\n"
