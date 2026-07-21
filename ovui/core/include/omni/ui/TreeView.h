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

#include "ItemModelHelper.h"

#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <unordered_map>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

class AbstractItemModel;
class AbstractItemDelegate;

/**
 * @brief TreeView is a widget that presents a hierarchical view of information. Each item can have a number of subitems.
 * An indentation often visualizes this in a list. An item can be expanded to reveal subitems, if any exist, and
 * collapsed to hide subitems.
 *
 * TreeView can be used in file manager applications, where it allows the user to navigate the file system directories.
 * They are also used to present hierarchical data, such as the scene object hierarchy.
 *
 * TreeView uses a model/view pattern to manage the relationship between data and the way it is presented. The
 * separation of functionality gives developers greater flexibility to customize the presentation of items and provides
 * a standard interface to allow a wide range of data sources to be used with other widgets.
 *
 * TreeView is responsible for the presentation of model data to the user and processing user input. To allow some
 * flexibility in the way the data is presented, the creation of the sub-widgets is performed by the delegate. It
 * provides the ability to customize any sub-item of TreeView.
 */
class OMNIUI_CLASS_API TreeView : public Widget, public ItemModelHelper
{
    OMNIUI_OBJECT(TreeView)

public:
    OMNIUI_API
    ~TreeView() override;

    /**
     * @brief Reimplemented the method to indicate the width hint that represents the preferred size of the widget.
     *
     * @see Widget::setComputedContentWidth
     */
    OMNIUI_API
    void setComputedContentWidth(float width) override;

    /**
     * @brief Reimplemented the method to indicate the height hint that represents the preferred size of the widget.
     *
     * @see Widget::setComputedContentHeight
     */
    OMNIUI_API
    void setComputedContentHeight(float height) override;

    /**
     * @brief Reimplemented the method from ItemModelHelper that is called when the model is changed.
     *
     * @param item The item in the model that is changed. If it's NULL, the root is chaged.
     */
    OMNIUI_API
    void onModelUpdated(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item) override;

    /**
     * @brief Deselects all selected items.
     */
    OMNIUI_API
    void clearSelection();

    /**
     * @brief Set current selection.
     */
    OMNIUI_API
    void setSelection(std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>> items);

    /**
     * @brief Switches the selection state of the given item.
     */
    OMNIUI_API
    void toggleSelection(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item);

    /**
     * @brief Extends the current selection selecting all the items between currently selected nodes and the given item.
     * It's when user does shift+click.
     */
    OMNIUI_API
    void extendSelection(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item);

    /**
     * @brief Return the list of selected items.
     */
    OMNIUI_API
    const std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>>& getSelection();

    /**
     * @brief Set the callback that is called when the selection is changed.
     */
    OMNIUI_CALLBACK(SelectionChanged, void, std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>>);

    /**
     * @brief Sets the function that will be called when the user use mouse enter/leave on the item.
     * function specification is the same as in setItemHovedFn.
     *     void onItemHovered(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item, bool hovered)
     */
    OMNIUI_CALLBACK(HoverChanged, void, std::shared_ptr<const AbstractItemModel::AbstractItem>, bool);

    /**
     * @brief Returns true if the given item is expanded.
     */
    OMNIUI_API
    bool isExpanded(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item);

    /**
     * @brief Sets the given item expanded or collapsed.
     *
     * @param item The item to expand or collapse.
     * @param expanded True if it's necessary to expand, false to collapse.
     * @param recursive True if it's necessary to expand children.
     */
    OMNIUI_API
    void setExpanded(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item, bool expanded, bool recursive);

    /**
     * @brief When called, it will make the delegate to regenerate all visible widgets the next frame.
     */
    OMNIUI_API
    void dirtyWidgets();

    /**
     * @brief The Item delegate that generates a widget per item.
     */
    OMNIUI_PROPERTY(std::shared_ptr<AbstractItemDelegate>,
                    delegate,
                    WRITE,
                    setDelegate,
                    PROTECTED,
                    READ,
                    getDelegate,
                    NOTIFY,
                    setDelegateChangedFn);

    /**
     * @brief Widths of the columns. If not set, the width is Fraction(1).
     */
    OMNIUI_PROPERTY(std::vector<Length>, columnWidths, READ, getColumnWidths, WRITE, setColumnWidths);

    /**
     * @brief When true, the columns can be resized with the mouse.
     */
    OMNIUI_PROPERTY(bool, columnsResizable, DEFAULT, false, READ, isColumnsResizable, WRITE, setColumnsResizable);

    /**
     * @brief This property holds if the header is shown or not.
     */
    OMNIUI_PROPERTY(bool, headerVisible, DEFAULT, false, READ, isHeaderVisible, WRITE, setHeaderVisible);

    /**
     * @brief This property holds if the root is shown. It can be used to make a single level tree appear like a simple
     * list.
     */
    OMNIUI_PROPERTY(
        bool, rootVisible, DEFAULT, true, READ, isRootVisible, WRITE, setRootVisible, NOTIFY, setRootVisibleChangedFn);

    /**
     * @brief This flag allows to prevent expanding when the user clicks the plus icon. It's used in the case the user
     * wants to control how the items expanded or collapsed.
     */
    OMNIUI_PROPERTY(bool, expandOnBranchClick, DEFAULT, true, READ, isExpandOnBranchClick, WRITE, setExpandOnBranchClick);

    /**
     * @brief When true, a single selected item is automatically scrolled into view.
     */
    OMNIUI_PROPERTY(bool, autoScrollSelection, DEFAULT, true, READ, isAutoScrollSelection, WRITE, setAutoScrollSelection);

    /**
     * @brief When true, the tree nodes are never destroyed even if they are disappeared from the model. It's useul for
     * the temporary filtering if it's necessary to display thousands of nodes.
     */
    OMNIUI_PROPERTY(bool, keepAlive, DEFAULT, false, READ, isKeepAlive, WRITE, setKeepAlive);

    /**
     * @brief Expand all the nodes and keep them expanded regardless their state.
     */
    OMNIUI_PROPERTY(
        bool, keepExpanded, DEFAULT, false, READ, isKeepExpanded, WRITE, setKeepExpanded, NOTIFY, setKeepExpandedChangedFn);

    /**
     * @brief When true, the tree nodes can be dropped between items.
     */
    OMNIUI_PROPERTY(bool, dropBetweenItems, DEFAULT, false, READ, isDropBetweenItems, WRITE, setDropBetweenItems);

    /**
     * @brief The expanded state of the root item. Changing this flag doesn't make the children repopulated.
     */
    OMNIUI_PROPERTY(bool,
                    rootExpanded,
                    DEFAULT,
                    true,
                    READ,
                    isRootExpanded,
                    WRITE,
                    setRootExpanded,
                    PROTECTED,
                    NOTIFY,
                    _setRootExpandedChangedFn);

    /**
     * @brief Minimum widths of the columns. If not set, the minimum width is Pixel(0).
     */
    OMNIUI_PROPERTY(std::vector<Length>, minColumnWidths, READ, getMinColumnWidths, WRITE, setMinColumnWidths);

    /**
     * @brief When true, the treeview is resizable when columns are resized. Otherwise, treeview width is fixed when columns are resized.
     */
    OMNIUI_PROPERTY(bool, resizableOnColumnsResized, DEFAULT, false, READ, isResizableOnColumnsResized, WRITE, setResizableOnColumnsResized);

    /**
     * @brief List of the flags that indicate if the column is fixed width.
     */
    OMNIUI_PROPERTY(std::vector<bool>, fixedWidthColumns, READ, getfixedWidthColumns, WRITE, setfixedWidthColumns);

protected:
    /**
     * @brief Create TreeView with the given model.
     *
     * @param model The given model.
     */
    OMNIUI_API
    TreeView(const std::shared_ptr<AbstractItemModel>& model = {});

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

private:
    friend class Inspector;
    struct Node;
    struct TreeViewData;
    enum class DropLocation : uint8_t;

    /**
     * @brief Populate the children of the given node. Usually, it's called when the user presses the expand button the
     * first time.
     */
    void _populateNodeChildren(struct Node* node);

    /**
     * @brief Calls _populateNodeChildren in every expanded node. Usually, _populateNodeChildren is called in a draw
     * cycle. But sometimes it's necessary to call it immediately for example when the model is changed and draw cycle
     * didn't happen yet.
     */
    void _populateNodeChildrenRecursive(TreeView::Node* node);

    /**
     * @brief Populate the widgets of the given node. It's called when the user presses the expand button the first time
     * and when the node is expanded or collapsed.
     */
    void _populateNodeWidget(TreeView::Node* node);

    /**
     * @brief It's only used in Inspector to make sure all the widgets prepopulated
     */
    void _populateNodeWidgetsRecursive(TreeView::Node* node);

    /**
     * @brief Populate the widgets of the header.
     */
    void _populateHeader();

    /**
     * @brief Compute width of the header widgets.
     */
    void _setHeaderComputedWidth();

    /**
     * @brief Compute height of the header widgets.
     */
    void _setHeaderComputedHeight(float& headerHeight);

    /**
     * @brief Recursively draw the widgets of the given node.
     */
    float _drawNodeInTable(const std::unique_ptr<Node>& node,
                           const std::unique_ptr<Node>& parent,
                           uint32_t hoveringColor,
                           uint32_t hoveringBorderColor,
                           uint32_t backgroundColor,
                           uint32_t dropIndicatorColor,
                           uint32_t dropIndicatorBorderColor,
                           float dropIndicatorThickness,
                           float cursorAtBeginTableX,
                           float cursorAtBeginTableY,
                           float currentOffset,
                           bool blockMouse,
                           float elapsedTime);

    /**
     * @brief Set computed width of the node and its children.
     */
    void _setNodeComputedWidth(const std::unique_ptr<Node>& node);

    /**
     * @brief Set computed height of the node and its children.
     */
    bool _setNodeComputedHeight(const std::unique_ptr<Node>& node, float& offset);

    /**
     * @brief Fills m_columnComputedSizes with absolute widths using property columnWidths.
     */
    float _computeColumnWidths(float width);

    /**
     * @brief Return the node that corresponds to the given model item.
     *
     * This is the internal function that shouldn't be called from outside because it's not guaranteed that the returned
     * object is valid for the next draw call.
     */
    Node* _getNode(const std::unique_ptr<TreeView::Node>& node,
                   const std::shared_ptr<const AbstractItemModel::AbstractItem>& item) const;

    /**
     * @brief Return the node that corresponds to the given model item.
     *
     * This is the internal function that shouldn't be called from outside because it's not guaranteed that the returned
     * object is valid for the next draw call.
     */
    Node* _getNode(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item) const;

    /**
     * @brief Fills gived list with the flat list of the nodes. Only expanded nodes are considered.
     *
     * @param root The node to start the flat list from.
     * @param list The list where the noreds are written.
     */
    void _createFlatNodeList(std::unique_ptr<TreeView::Node>& root, std::vector<std::unique_ptr<Node>*>& list) const;

    /**
     * @brief Deselects the given node and the children.
     */
    static void _clearNodeSelection(std::unique_ptr<TreeView::Node>& node);

    /**
     * @brief Called by TreeView when the selection is changed. It calls callbacks if they exist.
     */
    void _onSelectionChanged();

    /**
     * @brief It is called every frame to check if it's necessary to draw Drag And Drop highlight. Returns true if the
     * node needs highlight.
     */
    bool _hasAcceptedDrop(const std::unique_ptr<TreeView::Node>& node,
                          const std::unique_ptr<TreeView::Node>& parent,
                          DropLocation dropLocation) const;

    /**
     * @brief This function converts the flat drop location (above-below-over) on the table to the tree's location.
     *
     * When the user drops an item, he drops it between rows. And we need to know the child index that corresponds to
     * the parent into which the new rows are inserted.
     *
     * @param node The node the user droped something.
     * @param parent The parent of the node the user droped it.
     * @param dropLocation Above-below-over position in the table.
     * @param dropNode Output. The parent node into which the new item should be inserted.
     * @param dropId Output. The index of child the new item should be inserted. If -1, the new item should be inseted
     * to the end.
     */
    static void _getDropNode(const TreeView::Node* node,
                             const TreeView::Node* parent,
                             DropLocation dropLocation,
                             TreeView::Node const** dropNode,
                             int32_t& dropId);

    /**
     * @brief Sets the given node expanded or collapsed. It immidiatley populates children which is very useful when
     * doing search in the tree.
     *
     * @see TreeView::setExpanded
     */
    void _setExpanded(TreeView::Node* node, bool expanded, bool recursive, bool pouplateChildren = true);

    /**
     * @brief Checks both the state of the node and the `keepExpanded` property.
     */
    bool _isExpanded(TreeView::Node* node) const;

    /**
     * @brief Makes the widget and his children dirty. Dirty means that whe widget will be regenerated only if the node
     * is visible.
     */
    void _setWidgetsDirty(TreeView::Node* node, bool dirty, bool recursive) const;

    /**
     * @brief Called when the user started dragging the node. It generates drag and drop buffers.
     */
    void _beginDrag(TreeView::Node* node);

    /**
     * @brief Called when the user is dragging the node. It draws the widgets the user drags.
     */
    void _drawDrag(float elapsedTime, uint32_t backgroundColor) const;

    /**
     * @brief Called when the user droped the node. It cleans up the drag and drop caches. It doesn't send anything to
     * the model because it's closing _beginDrag. And it will be called even if the user drops it somwhere else. The
     * code that sends the drop notification is in TreeView::_drawNodeInTable because it should accept drag and drop
     * from other widgets.
     */
    void _endDrag() const;

    /**
     * @brief Calls drop with the model on the given node.
     *
     * @param node The node that accepted drop.
     */
    void _dragDropTarget(TreeView::Node* node, TreeView::Node* parent) const;

    /**
     * @brief Called by Inspector to inspect all the children.
     */
    std::vector<std::shared_ptr<Widget>> _getChildren();

    std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>> _payloadToItems(const void* payload) const;

    bool _setSelection(std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>> items);
    void _extendSelection(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item);
    void _toggleSelection(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item);
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
