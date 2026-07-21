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

#include <omni/ui/AbstractItemModel.h>
#include <omni/ui/TreeView.h>
#include <omni/ui/bind/BindTreeView.h>
#include <omni/ui/bind/BindUtils.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapTreeView(module& m)
{
    constexpr const char* treeViewDoc = OMNIUI_PYBIND_CLASS_DOC(TreeView);
    static constexpr char treeViewConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(TreeView, TreeView);

    class_<TreeView, Widget, ItemModelHelper, std::shared_ptr<TreeView>>(m, "TreeView", treeViewDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(TreeView); }), "Create TreeView with default model.")
        .def(init([](const std::shared_ptr<AbstractItemModel>& model, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(TreeView, model);
             }),
             treeViewConstructorDoc)
        .def("clear_selection", &TreeView::clearSelection, OMNIUI_PYBIND_DOC_TreeView_clearSelection)
        .def("toggle_selection", &TreeView::toggleSelection, arg("item"), OMNIUI_PYBIND_DOC_TreeView_toggleSelection)
        .def("extend_selection", &TreeView::extendSelection, arg("item"), OMNIUI_PYBIND_DOC_TreeView_extendSelection)
        .OMNIUI_PYBIND_DEF_CALLBACK(selection_changed, TreeView, SelectionChanged)
        .OMNIUI_PYBIND_DEF_CALLBACK(hover_changed, TreeView, HoverChanged)
        .def("is_expanded", &TreeView::isExpanded, arg("item"), OMNIUI_PYBIND_DOC_TreeView_isExpanded)
        .def("set_expanded", &TreeView::setExpanded, arg("item"), arg("expanded"), arg("recursive"),
             OMNIUI_PYBIND_DOC_TreeView_setExpanded)
        .def("dirty_widgets", &TreeView::dirtyWidgets, OMNIUI_PYBIND_DOC_TreeView_dirtyWidgets)
        .def_property("header_visible", &TreeView::isHeaderVisible, &TreeView::setHeaderVisible,
                      OMNIUI_PYBIND_DOC_TreeView_headerVisible)
        .def_property(
            "root_visible", &TreeView::isRootVisible, &TreeView::setRootVisible, OMNIUI_PYBIND_DOC_TreeView_rootVisible)
        .def_property(
            "selection", &TreeView::getSelection, &TreeView::setSelection, OMNIUI_PYBIND_DOC_TreeView_setSelection)
        .def_property("expand_on_branch_click", &TreeView::isExpandOnBranchClick, &TreeView::setExpandOnBranchClick,
                      OMNIUI_PYBIND_DOC_TreeView_expandOnBranchClick)
        .def_property("auto_scroll_selection", &TreeView::isAutoScrollSelection, &TreeView::setAutoScrollSelection,
                      OMNIUI_PYBIND_DOC_TreeView_autoScrollSelection)
        .def_property("keep_alive", &TreeView::isKeepAlive, &TreeView::setKeepAlive, OMNIUI_PYBIND_DOC_TreeView_keepAlive)
        .def_property("keep_expanded", &TreeView::isKeepExpanded, &TreeView::setKeepExpanded,
                      OMNIUI_PYBIND_DOC_TreeView_keepExpanded)
        .def_property("drop_between_items", &TreeView::isDropBetweenItems, &TreeView::setDropBetweenItems,
                      OMNIUI_PYBIND_DOC_TreeView_dropBetweenItems)
        .def_property("column_widths", &TreeView::getColumnWidths, &TreeView::setColumnWidths,
                      OMNIUI_PYBIND_DOC_TreeView_columnWidths)
        .def_property("min_column_widths", &TreeView::getMinColumnWidths, &TreeView::setMinColumnWidths,
                      OMNIUI_PYBIND_DOC_TreeView_minColumnWidths)
        .def_property("columns_resizable", &TreeView::isColumnsResizable, &TreeView::setColumnsResizable,
                      OMNIUI_PYBIND_DOC_TreeView_columnsResizable)
        .def_property("resizeable_on_columns_resized", &TreeView::isResizableOnColumnsResized, &TreeView::setResizableOnColumnsResized,
                     OMNIUI_PYBIND_DOC_TreeView_resizableOnColumnsResized)
        .def_property("fixed_width_columns", &TreeView::getfixedWidthColumns, &TreeView::setfixedWidthColumns,
                      OMNIUI_PYBIND_DOC_TreeView_fixedWidthColumns)
        .def_property("root_expanded", &TreeView::isRootExpanded, &TreeView::setRootExpanded,
                      OMNIUI_PYBIND_DOC_TreeView_rootExpanded)
        /* */;
}
