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

#include "BindUtils.h"
#include "BindWidget.h"
#include "DocTreeView.h"

#include <omni/ui/AbstractItemDelegate.h>

// clang-format off
#define OMNIUI_PYBIND_INIT_TreeView                                                                                    \
    OMNIUI_PYBIND_INIT_Widget                                                                                          \
    OMNIUI_PYBIND_INIT_CAST(delegate, setDelegate, std::shared_ptr<AbstractItemDelegate>)                              \
    OMNIUI_PYBIND_INIT_CAST(header_visible, setHeaderVisible, bool)                                                    \
    OMNIUI_PYBIND_INIT_CAST(root_visible, setRootVisible, bool)                                                        \
    OMNIUI_PYBIND_INIT_CAST(selection, setSelection, std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>>)              \
    OMNIUI_PYBIND_INIT_CAST(expand_on_branch_click, setExpandOnBranchClick, bool)                                      \
    OMNIUI_PYBIND_INIT_CAST(keep_alive, setKeepAlive, bool)                                                            \
    OMNIUI_PYBIND_INIT_CAST(keep_expanded, setKeepExpanded, bool)                                                      \
    OMNIUI_PYBIND_INIT_CAST(drop_between_items, setDropBetweenItems, bool)                                             \
    OMNIUI_PYBIND_INIT_CALL(column_widths, setColumnWidths, toLengths)                                                 \
    OMNIUI_PYBIND_INIT_CALL(min_column_widths, setMinColumnWidths, toLengths)                                          \
    OMNIUI_PYBIND_INIT_CAST(columns_resizable, setColumnsResizable, bool)                                              \
    OMNIUI_PYBIND_INIT_CAST(resizeable_on_columns_resized, setResizableOnColumnsResized, bool)                         \
    OMNIUI_PYBIND_INIT_CAST(fixed_width_columns, setfixedWidthColumns, std::vector<bool>)                  \
    OMNIUI_PYBIND_INIT_CAST(root_expanded, setRootExpanded, bool)                                                      \
    OMNIUI_PYBIND_INIT_CALLBACK(                                                                                       \
        selection_changed_fn, setSelectionChangedFn, void(std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>>))

#define OMNIUI_PYBIND_KWARGS_DOC_TreeView                                                                              \
    "\n    `delegate : `\n        "                                                                                    \
    OMNIUI_PYBIND_DOC_TreeView_delegate                                                                                \
    "\n    `header_visible : `\n        "                                                                              \
    OMNIUI_PYBIND_DOC_TreeView_headerVisible                                                                           \
    "\n    `selection : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_TreeView_setSelection                                                                            \
    "\n    `expand_on_branch_click : `\n        "                                                                      \
    OMNIUI_PYBIND_DOC_TreeView_expandOnBranchClick                                                                     \
    "\n    `keep_alive : `\n        "                                                                                  \
    OMNIUI_PYBIND_DOC_TreeView_keepAlive                                                                               \
    "\n    `keep_expanded : `\n        "                                                                               \
    OMNIUI_PYBIND_DOC_TreeView_keepExpanded                                                                            \
    "\n    `drop_between_items : `\n        "                                                                          \
    OMNIUI_PYBIND_DOC_TreeView_dropBetweenItems                                                                        \
    "\n    `column_widths : `\n        "                                                                               \
    OMNIUI_PYBIND_DOC_TreeView_columnWidths                                                                            \
    "\n    `min_column_widths : `\n        "                                                                           \
    OMNIUI_PYBIND_DOC_TreeView_minColumnWidths                                                                         \
    "\n    `columns_resizable : `\n        "                                                                           \
    OMNIUI_PYBIND_DOC_TreeView_columnsResizable                                                                        \
    "\n    `selection_changed_fn : `\n        "                                                                        \
    OMNIUI_PYBIND_DOC_TreeView_SelectionChanged                                                                        \
    "\n    `root_expanded : `\n        "                                                                               \
    OMNIUI_PYBIND_DOC_TreeView_rootExpanded                                                                            \
    OMNIUI_PYBIND_KWARGS_DOC_Widget
// clang-format on

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Convert Python list to vector of lengths.
 */
inline std::vector<Length> toLengths(const pybind11::handle& obj)
{
    using namespace pybind11;

    if (!isinstance<list>(obj))
    {
        return {};
    }

    const auto& objList = obj.cast<list>();

    std::vector<Length> result;
    result.reserve(objList.size());

    for (const auto& it : objList)
    {
        result.push_back(toLength(it));
    }

    return result;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
