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

#include "platform/Assert.h"
#include <cstring>
#include <limits>
#include "platform/Log.h"

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/AbstractItemDelegate.h>
#include <omni/ui/AbstractValueModel.h>
#include <omni/ui/Frame.h>
#include <omni/ui/HStack.h>
#include <omni/ui/Inspector.h>
#include <omni/ui/InvisibleButton.h>
#include <omni/ui/Label.h>
#include <omni/ui/Profile.h>
#include <omni/ui/Rectangle.h>
#include <omni/ui/SimpleListModel.h>
#include <omni/ui/Spacer.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/TreeView.h>
#include <omni/ui/VStack.h>
#include <omni/ui/ZStack.h>
#include <omni/ui/ScrollingFrame.h>

#include "WidgetData.h"

#include <algorithm>

OMNIUI_NAMESPACE_OPEN_SCOPE

static constexpr char g_contentDropType[] = "AssetDragDropPayloadId";

/**
 * @brief The location of Drag and Drop.
 *
 * Specifies where exactly the user droped the item.
 */
enum class TreeView::DropLocation : uint8_t
{
    eOver = 0,
    eAbove,
    eBelow,
    eUndefined,
};

struct TreeView::Node
{
    // Child nodes
    std::vector<std::unique_ptr<Node>> children;
    // Root level widget per column
    std::vector<std::shared_ptr<Widget>> widgets;
    // Branch + widget the user created in the delegate for the inspector
    std::vector<std::pair<std::shared_ptr<Widget>, std::shared_ptr<Widget>>> widgetsForInspector;
    // The state of the node. If it's false, then it's necessary to skip all the children.
    bool expanded = false;
    // True if it already has correct children.
    bool childrenPopulated = false;
    // True if it already has correct widgets. Not populated means it will be reconstructed the next frame.
    bool widgetsPopulated = false;
    // Dirty means it it will be reconstructed only if it's visible.
    bool widgetsDirty = false;
    // The corresponding item in the model.
    std::shared_ptr<const AbstractItemModel::AbstractItem> item = nullptr;
    // The indentation level
    uint32_t level = 0;
    // Selection state
    bool selected = false;
    // Flag if the widget size was already comuted and it doesn't require to be computed more. We need it to be able
    // to compute the size only of visible widgets.
    // This is the flag for _setNodeComputedWidth/_setNodeComputedHeight
    bool widthComputed = false;
    bool heightComputed = false;
    // Cached size of widgets
    float nodeHeight = 0.0f;
    // Cached position of widgets
    float positionOffset = 0.0f;
    // Indicates that the user drags this node
    bool dragInProgress = false;
    // True when the mouse already entered the drag and drop zone of this node and dropAccepted has the valid value.
    DropLocation dragEntered = DropLocation::eUndefined;
    // True if the current drag and drop can be accepted by the current model.
    bool dropAccepted = false;
    // When keepAlive is true, the nodes are never removed. Instead or removing, TreeView makes active = false and
    // such nodes are not drawing.
    bool active = true;
    // True if mouse hover on this node
    bool hovered = false;
};

struct TreeView::TreeViewData : public Widget::WidgetData
{
    TreeViewData() : m_root(new Node) {}
    ~TreeViewData() override = default;

    // The main cache of this widget. It has everything that this widget draws including the hirarchy of the nodes and
    // the widgets they have.
    std::unique_ptr<Node> m_root;

    // Cache to quick query item node.
    std::unordered_map<const AbstractItemModel::AbstractItem*, Node*> m_itemNodeCache;

    // The cached number of columns.
    size_t m_columnsCount = 0;

    // Absolute widths of each column.
    std::vector<float> m_columnComputedSizes;

    // Absolute minimum widths of each column.
    std::vector<float> m_minColumnComputedSizes;

    // The list of the selected items. Vector because the selection order is important.
    std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>> m_selection;

    // Callback when the selection is changed
    std::function<void(std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>>)> m_selectionChangedFn;

    // Callback when item hover status is changed
    std::function<void(std::shared_ptr<const AbstractItemModel::AbstractItem>, bool)> m_hoverChangedFn;

    // Header widgets
    std::vector<std::shared_ptr<Frame>> m_headerWidgets;
    bool m_headerPopulated = false;

    // When the node is just selected, it used to scroll the tree view to the node.
    Node* m_scrollHere = nullptr;

    // Drag and drop caches.
    mutable std::unique_ptr<char[]> m_dragAndDropPayloadBuffer;
    mutable size_t m_dragAndDropPayloadBufferSize;
    mutable std::vector<const Node*> m_dragAndDropNodes;

    // False when internal Node structures are not synchronized with the model. Nodes are synchronized during the draw
    // loop.
    bool m_modelSynchronized = false;

    // Indicates that at least one node has heightComputed false
    bool m_contentHeightDirty = true;

    // Sum of all columns
    float m_contentWidth = 0.0f;

    // Indicates that content width has changed, will cause force recomputation for tree node width
    bool m_contentWidthDirty = false;

    // Height of internal content
    float m_contentHeight = 0.f;

    // Relative Y position of visible area
    float m_relativeRectMin = 0.f;
    float m_relativeRectMax = 0.f;

    // The variables to find the average of all the widgets created. We need it to assume the total length of the
    // TreeView without creating the widgets.
    float m_sumHeights = 0.f;
    uint64_t m_numHeights = 0;

    // Cached desired minimum width (pixels) for the last column measured during draw.
    float m_lastColumnMeasuredMinPx = 0.0f;

    // If the column is resizing at this moment, it is the id of the right column. When 0, no resize happens.
    uint32_t m_resizeColumn = 0;

    // We need it for autoscrolling when drag and drop. Since ImGui rounds pixel, we can only scroll with int values,
    // and when FPS is very high, it doesn't scroll at all. We accumulate the small scrolling to this variable.
    float m_accumulatedAutoScroll = 0.0f;
};

/**
 * @brief Extract the pointers to the items from the payload.
 */
std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>> TreeView::_payloadToItems(const void* ptr) const
{
    auto& data = _getData<TreeViewData>();

    const ImGuiPayload* payload = reinterpret_cast<const ImGuiPayload*>(ptr);

    OMNIUI_ASSERT(payload->IsDataType(Widget::getDragDropPayloadId()));

    // Payload has the MIME data followed by the pointers to the items at the end. We need to skip the string and
    // extract the pointers.
    const size_t payloadSize = payload->DataSize; // This includes the c-string trailing '\0'
    if (payloadSize <= 1)
    {
        return {};
    }

    const char* mimeData = reinterpret_cast<const char*>(payload->Data);
    size_t mimeDataSize = strnlen(mimeData, payloadSize) + 1;
    if (mimeDataSize >= payloadSize)
    {
        // There is nothing after string and it means the payload is not from tree view.
        return {};
    }

    constexpr size_t itemPointerSize = sizeof(AbstractItemModel::AbstractItem*);
    size_t itemCount = (payload->DataSize - mimeDataSize) / itemPointerSize;

    std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>> result;
    result.reserve(itemCount);
    for (size_t i = 0; i < itemCount; ++i)
    {
        AbstractItemModel::AbstractItem* item =
            *reinterpret_cast<AbstractItemModel::AbstractItem* const*>(mimeData + mimeDataSize + i * itemPointerSize);
        auto found = data.m_itemNodeCache.find(item);
        if (found != data.m_itemNodeCache.end())
        {
            result.push_back(found->second->item);
        }
    }

    return result;
}

/**
 * @brief Default delegate that creates Labels from the model.
 */
class DefaultItemDelegate : public AbstractItemDelegate
{
public:
    static std::shared_ptr<DefaultItemDelegate> create()
    {
        return std::shared_ptr<DefaultItemDelegate>{ new DefaultItemDelegate{} };
    }

    ~DefaultItemDelegate() override = default;

    void buildBranch(const std::shared_ptr<AbstractItemModel>& model,
                     const std::shared_ptr<const AbstractItemModel::AbstractItem>& item = nullptr,
                     size_t index = 0,
                     uint32_t level = 0,
                     bool expanded = false) override
    {
        if (OMNIUI_UNLIKELY(static_cast<bool>(model) == false))
        {
            return;
        }
        if (index != 0)
        {
            return;
        }

        auto hstack = HStack::create();
        hstack->setWidth(Pixel(15.0f * level));
        OMNIKIT_WITH_CONTAINER(hstack)
        {
            Spacer::create();
            if (model->canItemHaveChildren(item))
            {
                auto label = Label::create(expanded ? "-" : "+");
                label->setWidth(Pixel(10.0f));
                label->setStyleTypeNameOverride("TreeView.Item");
            }
        }
    }

    void buildWidget(const std::shared_ptr<AbstractItemModel>& model,
                     const std::shared_ptr<const AbstractItemModel::AbstractItem>& item = nullptr,
                     size_t index = 0,
                     uint32_t level = 0,
                     bool expanded = false) override
    {
        if (OMNIUI_UNLIKELY(static_cast<bool>(model) == false))
        {
            return;
        }

        auto valueModel = model->getItemValueModel(item, index);
        if (valueModel)
        {
            auto label = Label::create(valueModel->getValueAsString());
            label->setStyleTypeNameOverride("TreeView.Item");

            // Since the label widget is not the model widget, we need to change its value in the model callback.
            std::weak_ptr<Label> labelWeak{ label };
            valueModel->addValueChangedFn(
                [labelWeak](const AbstractValueModel* valueModel)
                {
                    // Check if the label is still alive.
                    auto label = labelWeak.lock();
                    if (label)
                    {
                        label->setText(valueModel->getValueAsString());
                    }
                });
        }
    }

    void buildHeader(size_t index = 0) override
    {
        // TODO: We need to decide which objects holds the header names
    }

protected:
    DefaultItemDelegate() = default;
};


TreeView::TreeView(const std::shared_ptr<AbstractItemModel>& model)
    : Widget(new TreeViewData)
    , ItemModelHelper(model)
{
    if (!model)
    {
        // If there is no model, create a simple one.
        auto model = SimpleListModel::create(std::vector<std::string>{ { "first", "second", "hello", "world" } });
        this->setModel(model);
    }
    else
    {
        // We can't call it from the base class because it's not possible to call inherited methods in the constructor.
        this->onModelUpdated(nullptr);
    }

    // Apply the default model.
    this->setDelegate(DefaultItemDelegate::create());

    // Root is expanded by default
    _getData<TreeViewData>().m_root->expanded = this->isRootExpanded();

    // Mark all the widgets dirty when keep expanded changed, because we need to redraw the +/- icon when the objects
    // are collapsing.
    this->setKeepExpandedChangedFn([this](const bool& keep) { this->dirtyWidgets(); });

    // Mark all the widgets dirty when rootVisible is changed to redraw them because the offset is changed
    this->setRootVisibleChangedFn([this](const bool& rootVisible) { this->dirtyWidgets(); });

    // Set expanded root with no pupulation of children.
    this->_setRootExpandedChangedFn([this](const bool& expanded) {
        this->_setExpanded(_getData<TreeViewData>().m_root.get(), expanded, false, false);
    });
}

TreeView::~TreeView() = default;

void TreeView::setComputedContentWidth(float width)
{
    auto& data = _getData<TreeViewData>();

    // Compute column widths first.
    width = this->_computeColumnWidths(width);
    if (width != this->getComputedContentWidth())
    {
        data.m_contentWidth = width;
        // When content width has changed, mark it as dirty and force node width recomputation
        data.m_contentWidthDirty = true;
    }

    this->_populateHeader();
    this->_setHeaderComputedWidth();

    this->_setNodeComputedWidth(data.m_root);
    Widget::setComputedContentWidth(width);
    data.m_contentWidthDirty = false;
}

void TreeView::setComputedContentHeight(float height)
{
    auto& data = _getData<TreeViewData>();

    this->_populateHeader();
    float headerHeight = 0.f;
    this->_setHeaderComputedHeight(headerHeight);

    float contentHeight = 0.f;
    if (this->_setNodeComputedHeight(data.m_root, contentHeight))
    {
        data.m_contentHeight = contentHeight;
        data.m_contentHeightDirty = false;
    }

    Widget::setComputedContentHeight(std::max(height, data.m_contentHeight + headerHeight));
}

void TreeView::onModelUpdated(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
    auto node = this->_getNode(item);
    if (node)
    {
        // Next time it will be repopulated
        node->childrenPopulated = false;
        node->widgetsPopulated = false;
    }

    auto& data = _getData<TreeViewData>();
    if (item == nullptr)
    {
        // If root is changed, we need to find out the number of columns
        const auto& model = this->getModel();
        if (OMNIUI_LIKELY(static_cast<bool>(model)))
        {
            data.m_columnsCount = model->getItemValueModelCount(nullptr);
            data.m_columnComputedSizes.resize(data.m_columnsCount, 0.0f);
            data.m_minColumnComputedSizes.resize(data.m_columnsCount, 0.0f);
            data.m_headerPopulated = false;
        }
    }

    data.m_modelSynchronized = false;
    data.m_contentHeightDirty = true;

    this->forceWidthDirty(SizeDirtyReason::eSizeChanged);
    this->forceHeightDirty(SizeDirtyReason::eSizeChanged);
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void TreeView::clearSelection()
{
    auto& data = _getData<TreeViewData>();

    if (data.m_selection.empty())
    {
        return;
    }

    data.m_selection.clear();

    this->_clearNodeSelection(data.m_root);

    this->_onSelectionChanged();
}

void TreeView::setSelection(std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>> items)
{
    if (this->_setSelection(items))
    {
        this->_onSelectionChanged();
    }
}

bool TreeView::_setSelection(std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>> items)
{
    // Make sure it's a new selection.
    auto& data = _getData<TreeViewData>();
    if (data.m_selection == items)
    {
        return false;
    }

    // Clear all
    this->_clearNodeSelection(data.m_root);

    Node* node = nullptr;

    // Apply selection
    data.m_selection.swap(items);
    for (auto item : data.m_selection)
    {
        node = this->_getNode(item);
        if (node)
        {
            node->selected = true;

            for (auto& widget : node->widgets)
            {
                if (widget)
                {
                    widget->setSelected(true);
                }
            }
        }
    }

    if (data.m_selection.size() == 1)
    {
        // Scroll to the selection only if there is one object selected.
        data.m_scrollHere = node;
    }
    else if (data.m_scrollHere)
    {
        data.m_scrollHere = nullptr;
    }

    return true;
}

void TreeView::toggleSelection(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
    this->_toggleSelection(item);
    this->_onSelectionChanged();
}

void TreeView::_toggleSelection(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
    auto node = this->_getNode(item);
    if (!node)
    {
        return;
    }

    bool selected = !node->selected;
    node->selected = selected;

    for (auto& widget : node->widgets)
    {
        if (widget)
        {
            widget->setSelected(selected);
        }
    }

    auto& data = _getData<TreeViewData>();
    auto found = std::find(data.m_selection.begin(), data.m_selection.end(), item);
    if (found != data.m_selection.end())
    {
        data.m_selection.erase(found);
    }

    if (selected)
    {
        // If it was in the selection before, it's moved to the end of the selection.
        data.m_selection.push_back(item);
    }
}

void TreeView::extendSelection(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
    this->_extendSelection(item);
    this->_onSelectionChanged();
}

void TreeView::_extendSelection(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
    auto& data = _getData<TreeViewData>();

    // First we need all the nodes as a flat list.
    std::vector<std::unique_ptr<Node>*> flatNodes;
    this->_createFlatNodeList(data.m_root, flatNodes);

    // We need to know which node is the first node selected, the last node selected and the item it's necessary to
    // extend the selection to.
    size_t first = SIZE_MAX;
    size_t last = SIZE_MAX;
    size_t selected = SIZE_MAX;

    // Scan the list to find the first node selected, last node selected and the item it's necessary to extend the
    // selection to.
    for (size_t i = 0, n = flatNodes.size(); i < n; ++i)
    {
        auto& node = *flatNodes[i];

        // The first and the last one.
        if (node->selected)
        {
            if (first == SIZE_MAX)
            {
                first = i;
            }

            last = i;
        }

        // The selected one.
        if (node->item == item)
        {
            OMNIUI_ASSERT(selected == SIZE_MAX);
            selected = i;
        }

        // Deselect all previously selected.
        if (node->selected)
        {
            node->selected = false;
            for (auto& widget : node->widgets)
            {
                if (widget)
                {
                    widget->setSelected(false);
                }
            }
        }
    }

    if (first == SIZE_MAX)
    {
        // It happens if nothing is selected and the user press Shift-Select.
        first = selected;
    }

    if (last == SIZE_MAX)
    {
        // It happens if nothing is selected and the user press Shift-Select.
        last = selected;
    }

    data.m_selection.clear();

    // Second pass. Select the group.
    size_t from = std::min(first, selected);
    size_t to = std::max(selected, last);
    data.m_selection.reserve(to - from + 1);
    for (; from <= to; ++from)
    {
        auto& node = *flatNodes[from];

        node->selected = true;

        for (auto& widget : node->widgets)
        {
            if (widget)
            {
                widget->setSelected(true);
            }
        }

        data.m_selection.push_back(node->item);
    }
}

const std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>>& TreeView::getSelection()
{
    auto& data = _getData<TreeViewData>();
    if (!data.m_modelSynchronized)
    {
        // We are here because nodes don't match to the model. We need to populate them.
        this->_populateNodeChildrenRecursive(data.m_root.get());

        // Check if the selection has items that was removed from the model and remove such items from selection.
        for (auto it = data.m_selection.begin(); it != data.m_selection.end();)
        {
            auto node = this->_getNode(*it);
            if (!node)
            {
                it = data.m_selection.erase(it);
            }
            else
            {
                ++it;
            }
        }
    }

    return data.m_selection;
}

bool TreeView::isExpanded(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
    auto node = this->_getNode(item);
    if (!node)
    {
        return false;
    }

    return node->expanded;
}

void TreeView::setExpanded(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item, bool expanded, bool recursive)
{
    auto node = this->_getNode(item);
    if (!node)
    {
        return;
    }

    this->_setExpanded(node, expanded, recursive);
}

void TreeView::dirtyWidgets()
{
    this->_setWidgetsDirty(_getData<TreeViewData>().m_root.get(), true, true);
}

void TreeView::_drawContent(float elapsedTime)
{
    this->_populateHeader();

    uint32_t borderColor = 0x0;
    this->_resolveStyleProperty(StyleColorProperty::eSecondaryColor, &borderColor);
    uint32_t selectionBackgroundColor = 0x0;
    this->_resolveStyleProperty(
        StyleColorProperty::eBackgroundColor, StyleContainer::State::eSelected, &selectionBackgroundColor);
    uint32_t hoveringBackgroundColor = 0x0;
    this->_resolveStyleProperty(StyleColorProperty::eBackgroundSelectedColor, &hoveringBackgroundColor);
    uint32_t hoveringBorderColor = 0x0;
    this->_resolveStyleProperty(StyleColorProperty::eBorderColor, &hoveringBorderColor);
    uint32_t resizeControlColor = 0x0;
    this->_resolveStyleProperty(StyleColorProperty::eSecondarySelectedColor, &resizeControlColor);
    uint32_t dropBackgroundColor = 0x0;
    this->_resolveStyleProperty(StyleColorProperty::eBackgroundSelectedColor, StyleContainer::State::eDrop, &dropBackgroundColor);
    uint32_t dropBorderColor = selectionBackgroundColor;
    this->_resolveStyleProperty(StyleColorProperty::eBorderColor, StyleContainer::State::eDrop, &dropBorderColor);
    float dropIndicatorThickness = 1.0f;
    this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &dropIndicatorThickness);
    dropIndicatorThickness *= this->getDpiScale();

    auto cursorAtBeginTable = ImGui::GetCursorScreenPos();

    auto& data = _getData<TreeViewData>();
    OMNIUI_ASSERT(data.m_columnComputedSizes.size() == data.m_columnsCount);

    // Compute the header size
    float headerHeight = 0.0f;
    if (this->isHeaderVisible())
    {
        OMNIUI_ASSERT(data.m_headerWidgets.size() == data.m_columnsCount);

        for (size_t i = 0; i < data.m_columnsCount; ++i)
        {
            const auto& widget = data.m_headerWidgets[i];
            headerHeight = std::max(headerHeight, widget->getComputedHeight());
        }
    }

    auto* ctx = ImGui::GetCurrentContext();
    ImGuiWindow* window = ctx->CurrentWindow;
    bool blockMouse = window->Flags & ImGuiWindowFlags_NoMouseInputs;
    ImRect clipRect = window->ClipRect;
    // Y of visible area
    data.m_relativeRectMin = clipRect.Min.y - cursorAtBeginTable.y;
    data.m_relativeRectMax = clipRect.Max.y - cursorAtBeginTable.y;

    // Draw all nodes
    std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>> saved_selection = data.m_selection;
    this->_drawNodeInTable(data.m_root, {}, hoveringBackgroundColor, hoveringBorderColor, selectionBackgroundColor,
                           dropBackgroundColor, dropBorderColor, dropIndicatorThickness, cursorAtBeginTable.x,
                           cursorAtBeginTable.y, headerHeight, blockMouse, elapsedTime);
    if (data.m_selection != saved_selection)
    {
        // OMPE-61075: node drawing and model update may happen in different threads but at same time.
        // Then if selection changed during the node drawing, _onSelectionChanged will re-populate all tree nodes
        // which leads drawing node becomes invalid and crash happens.
        // So call _onSelectionChanged after all nodes are drawn.
        this->_onSelectionChanged();
    }

    // Gets cursor after drawing all nodes to check if mouse is over empty area.
    auto cursorAfterDrawingNodes = ImGui::GetCursorScreenPos();

    float computedContentWidth = this->getComputedContentWidth();
    float computedContentHeight = this->getComputedContentHeight();
    ImVec2 cursorAtEndTable{ cursorAtBeginTable.x + computedContentWidth, cursorAtBeginTable.y + data.m_contentHeight };
    ImGui::SetCursorScreenPos(cursorAtEndTable);

    auto drawList = ImGui::GetWindowDrawList();

    // Drag and drop to the empty space after tree nodes.
    ImVec2 emptySpaceMin{ cursorAtBeginTable.x, cursorAfterDrawingNodes.y };
    ImVec2 emptySpaceMax{ cursorAtBeginTable.x + computedContentWidth, cursorAtBeginTable.y + computedContentHeight };

    // Check if we have empty space
    if (emptySpaceMax.y > emptySpaceMin.y)
    {
        // Ouput invisible button because it's the item, _dragDropTarget needs an item. Plus we use it to deselect.
        ImGui::SetCursorScreenPos(emptySpaceMin);
        if (ImGui::InvisibleButton("", { emptySpaceMax.x - emptySpaceMin.x, emptySpaceMax.y - emptySpaceMin.y }))
        {
            this->clearSelection();
        }

        // If the root node has one child, drop there.
        // TODO: It's a temporary solution for Stage2 before release. We need to reconsider it asap.
        auto& dropNode = data.m_root->children.size() == 1 ? data.m_root->children.front() : data.m_root;
        if (!blockMouse && ImGui::IsMouseHoveringRect(emptySpaceMin, emptySpaceMax) &&
            this->_hasAcceptedDrop(dropNode, {}, DropLocation::eOver))
        {
            // Draw drop highlight
            ImVec2 start{ cursorAtBeginTable.x, cursorAtBeginTable.y + headerHeight + 1 };
            drawList->AddRect(
                start, emptySpaceMax, dropBorderColor, 0.0f, ImDrawFlags_RoundCornersAll, dropIndicatorThickness);

            // Drop
            this->_dragDropTarget(dropNode.get(), nullptr);
        }
    }

    if (this->isHeaderVisible() && clipRect.Min.y < std::max(emptySpaceMin.y, emptySpaceMax.y))
    {
        // Draw a sliding header on top of the table.
        OMNIUI_ASSERT(data.m_headerWidgets.size() == data.m_columnsCount);

        auto headerCursor = cursorAtBeginTable;
        // Follow the scrolling frame
        headerCursor.y = std::max(clipRect.Min.y, headerCursor.y);
        for (size_t i = 0; i < data.m_columnsCount; ++i)
        {
            ImGui::SetCursorScreenPos(headerCursor);

            const auto& widget = data.m_headerWidgets[i];
            widget->draw(elapsedTime);

            headerCursor.x += data.m_columnComputedSizes[i];
        }
    }

    // Measure last column desired width using visible nodes (first-level) and cache for next frame
    // Only when model just synchronized or content width considered dirty (to avoid per-frame work), and when within
    // a ScrollingFrame with horizontal scroll enabled
    if ((!data.m_modelSynchronized || data.m_contentWidthDirty) && data.m_columnsCount >= 1)
    {
        const size_t lastCol = data.m_columnsCount - 1;
        // Only when last column isn't fixed Pixel
        auto columnWidths = this->getColumnWidths();
        if (columnWidths.size() < data.m_columnsCount || columnWidths[lastCol].unit == UnitType::eFraction)
        {
            bool underScrollingFrame = false;
            bool horizOn = false;
            const Widget* ancestor = this;
            while (ancestor && !underScrollingFrame)
            {
                ancestor = ancestor->getParent();
                if (ancestor)
                {
                    if (auto sf = dynamic_cast<const ScrollingFrame*>(ancestor))
                    {
                        underScrollingFrame = true;
                        horizOn = (sf->getHorizontalScrollBarPolicy() != ScrollBarPolicy::eScrollBarAlwaysOff);
                    }
                }
            }

            if (underScrollingFrame && horizOn)
            {
                float measuredMinWidthPx = 0.0f;
                // Measure from visible root children area using computed widgets if available
                for (const auto& child : data.m_root->children)
                {
                    if (!child->widgets.empty() && lastCol < child->widgets.size())
                    {
                        auto& cell = child->widgets[lastCol];
                        if (cell)
                        {
                            measuredMinWidthPx = std::max(measuredMinWidthPx, cell->getComputedWidth());
                        }
                    }
                }
                if (measuredMinWidthPx > 0.0f)
                {
                    data.m_lastColumnMeasuredMinPx = measuredMinWidthPx;
                }
            }
        }
    }

    float dpiScale = this->getDpiScale();

    // Check if the user tries to resize the column
    uint32_t resizeColumn = 0;

    // The last thing to draw is the borders
    // Clipping the lines with window->ClipRect to avoid float precision artifacts when the table has a big number of
    // items (about 35,000)
    auto lineBegin = ImVec2{ cursorAtBeginTable.x, std::max(cursorAtBeginTable.y, window->ClipRect.Min.y) };
    auto lineEnd =
        ImVec2{ cursorAtBeginTable.x, std::min(window->ClipRect.Max.y, std::max(emptySpaceMin.y, emptySpaceMax.y)) };
    auto fixedWidthColumns = this->getfixedWidthColumns();
    std::vector<float> resizerXs;
    // If the fixedWidthColumns is not set correctly, we assume that all columns are resizable.
    if (fixedWidthColumns.size() != data.m_columnsCount)
    {
        fixedWidthColumns = std::vector<bool>(data.m_columnsCount, false);
    }

    for (size_t i = 0; i + 1 < data.m_columnsCount; ++i)
    {
        lineBegin.x += data.m_columnComputedSizes[i];
        lineEnd.x = lineBegin.x;
        resizerXs.push_back(lineBegin.x);

        // The resize area is 2 points wide
        ImVec2 resizeAreaMin{ lineBegin.x - dpiScale, lineBegin.y };
        ImVec2 resizeAreaMax{ lineEnd.x + dpiScale, lineEnd.y };

        bool hovered =
            !blockMouse && this->isColumnsResizable() && ImGui::IsMouseHoveringRect(resizeAreaMin, resizeAreaMax);
        if ((hovered || data.m_resizeColumn == i + 1) && !fixedWidthColumns[i])
        {
            drawList->AddRectFilled(resizeAreaMin, resizeAreaMax, resizeControlColor);
            ImGui::SetMouseCursor(ImGuiMouseCursor_ResizeEW);

            if (ImGui::IsMouseClicked(0))
            {
                resizeColumn = static_cast<uint32_t>(i + 1);
            }
        }
        else
        {
            drawList->AddLine(lineBegin, lineEnd, borderColor);
        }
    }

    if (data.m_resizeColumn == 0 && resizeColumn != 0)
    {
        // Resize started
        data.m_resizeColumn = resizeColumn;
    }

    if (data.m_resizeColumn != 0)
    {
        if (!ImGui::IsMouseDown(0))
        {
            // Resize finished
            data.m_resizeColumn = 0;
        }
        else
        {
            // Resize is in process
            const ImGuiIO& io = ImGui::GetIO();
            float delta = io.MouseDelta.x;

            if (delta != 0.0f)
            {
                auto widths = this->getColumnWidths();
                if (widths.size() != 0)
                {
                    size_t leftColumn = data.m_resizeColumn - 1;
                    size_t rightColumn = data.m_columnsCount - 1;
                    const float leftColumnComputedWidth = data.m_columnComputedSizes[leftColumn];
                    const float leftMinColumnComputedWidth = data.m_minColumnComputedSizes[leftColumn];
                    const float rightColumnComputedWidth = data.m_columnComputedSizes[rightColumn];
                    const float rightMinColumnComputedWidth = data.m_minColumnComputedSizes[rightColumn];

                    // If column size is less or equal to minimum width, stopping resize.
                    // make sure the mouse and the resizer is not detached
                    if (delta < 0.0f && leftColumnComputedWidth > leftMinColumnComputedWidth && resizerXs[leftColumn] - io.MousePos.x >= 0.0)
                    {
                        delta = std::max(leftMinColumnComputedWidth - leftColumnComputedWidth, delta);
                    }
                    // make sure the mouse and the resizer is not detached
                    else if (delta > 0.0f && rightColumnComputedWidth > rightMinColumnComputedWidth && io.MousePos.x - resizerXs[leftColumn] >= 0.0)
                    {
                        delta = std::min(rightColumnComputedWidth - rightMinColumnComputedWidth, delta);
                    }
                    else
                    {
                        delta = 0.0f;
                    }

                    if (delta != 0.0f)
                    {
                        if (this->isResizableOnColumnsResized())
                        {
                            // convert all the widths to pixels
                            for (unsigned int i = 0; i < data.m_columnsCount; ++i)
                            {
                                Length& length = widths[i];
                                if (length.unit != UnitType::ePixel)
                                {
                                    length = Pixel(data.m_columnComputedSizes[i]);
                                }
                            }

                            // only resize the left column
                            Length& leftLength = widths[leftColumn];
                            leftLength.value += delta;

                            this->forceWidthDirty(SizeDirtyReason::eSizeChanged);
                            this->setColumnWidths(widths);
                        }
                        else
                        {
                            // Since we have multiple units, we need to convert pixel delta to a fraction of the previous width.
                            float leftSizeFraction = 1.0f;
                            if (leftColumnComputedWidth != 0)
                            {
                                leftSizeFraction += delta / leftColumnComputedWidth;
                            }
                            float rightSizeFraction = 1.0f;
                            if (rightColumnComputedWidth != 0)
                            {
                                rightSizeFraction += -delta / rightColumnComputedWidth;
                            }
                            if (leftSizeFraction > 0.0f && rightSizeFraction > 0.0f)
                            {
                                // Apply new size. Since we have a fraction of the previous width, we don't care the units.
                                auto& leftLength = widths[leftColumn];
                                leftLength.value *= leftSizeFraction;

                                auto& rightLength = widths[rightColumn];
                                rightLength.value *= rightSizeFraction;

                                this->forceWidthDirty(SizeDirtyReason::eSizeChanged);
                                this->setColumnWidths(widths);
                            }
                        }
                    }
                }
                else
                {
                    OMNIUI_LOG_ERROR("Cannot resize TreeView column due to missing 'column_widths' parameter");
                }
            }
        }
    }

    const ImGuiPayload* payload = ImGui::GetDragDropPayload();
    if (data.m_dragAndDropPayloadBuffer && !payload)
    {
        this->_endDrag();
    }

    // Auto scroll when thre drag is active and the user hovers the mouse cursor the top or bottom area of the treeview.
    if (payload)
    {
        // The top/bottom area are 25% of the treeview area but not more than 25 pixels.
        float maxHeightPixels = 25.0f * dpiScale;
        constexpr float minHeightPortion = 0.25f;
        constexpr float speed = 500.0f;

        ImVec2 rectTopMin = cursorAtBeginTable;
        rectTopMin.x = std::max(clipRect.Min.x, rectTopMin.x);
        rectTopMin.y = std::max(clipRect.Min.y, rectTopMin.y);

        ImVec2 rectBottomMax = cursorAtEndTable;
        rectBottomMax.x = std::min(clipRect.Max.x, rectBottomMax.x);
        rectBottomMax.y = std::min(clipRect.Max.y, rectBottomMax.y);

        float dropAreaHeight = std::min((rectBottomMax.y - rectTopMin.y) * minHeightPortion, maxHeightPixels);

        ImVec2 rectTopMax{ rectBottomMax.x, rectTopMin.y + dropAreaHeight };
        ImVec2 rectBottomMin{ rectTopMin.x, rectBottomMax.y - dropAreaHeight };

        bool isHoveringTop = !blockMouse && ImGui::IsMouseHoveringRect(rectTopMin, rectTopMax);
        bool isHoveringBottom = !blockMouse && !isHoveringTop && ImGui::IsMouseHoveringRect(rectBottomMin, rectBottomMax);

        if (isHoveringTop)
        {
            // Since ImGui rounds pixel, scroll doesn't move if scrolling less than 1.0f a frame, so we need to keep the
            // accumulated scroll internally and add ImGui scroll rounded values.
            data.m_accumulatedAutoScroll -= speed * elapsedTime;
        }
        else if (isHoveringBottom)
        {
            data.m_accumulatedAutoScroll += speed * elapsedTime;
        }

        if (isHoveringTop || isHoveringBottom)
        {
            if (fabsf(data.m_accumulatedAutoScroll) > 1.0f)
            {
                float offset = floorf(data.m_accumulatedAutoScroll);
                float newScroll = ImGui::GetScrollY() + offset;
                // Clamp new scroll to [0, ScrollMaxY]
                newScroll = std::max(0.0f, std::min(ImGui::GetScrollMaxY(), newScroll));
                ImGui::SetScrollY(newScroll);

                data.m_accumulatedAutoScroll -= offset;
            }
        }
    }
    else if (data.m_accumulatedAutoScroll != 0.0f)
    {
        data.m_accumulatedAutoScroll = 0.0f;
    }

    if (!data.m_modelSynchronized)
    {
        data.m_modelSynchronized = true;
    }
}

void TreeView::_populateNodeChildren(TreeView::Node* node)
{
    OMNIUI_PROFILE_VERBOSE_WIDGET_FUNCTION;
    if (node->childrenPopulated)
    {
        return;
    }

    node->childrenPopulated = true;
    this->_setWidgetsDirty(node, true, false);

    // Move the old children to temporary location. We are using some of them if we still need them.
    std::unordered_map<const AbstractItemModel::AbstractItem*, std::unique_ptr<Node>> oldChildren;
    if (this->isKeepAlive())
    {
        // Keep Alive means we never destroy nodes. Instead we mark them non active they will be marked as active if
        // they stay in the model later in the code.
        for (const auto& child : node->children)
        {
            child->active = false;
        }
    }
    else
    {
        // Buffer the currenly existed nodes. They will be moved back to children if they are still in the model.
        // Non-moved nodes will be destroyed.
        for (auto& child : node->children)
        {
            oldChildren.insert({ child->item.get(), std::move(child) });
        }
        node->children.clear();
    }

    auto& data = _getData<TreeViewData>();

    // Populate children
    std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>> childItems;
    {
        const auto& model = this->getModel();
        if (OMNIUI_LIKELY(static_cast<bool>(model)))
        {
            childItems = model->getItemChildren(node->item);
        }
        else
        {
            OMNIUI_LOG_ERROR("TreeView::_populateNodeChildren called without a model");
        }
    }

    node->children.reserve(node->children.size() + childItems.size());

    for (const auto& childItem : childItems)
    {
        std::unique_ptr<Node> result;

        if (this->isKeepAlive())
        {
            auto existsIterator = data.m_itemNodeCache.find(childItem.get());
            if (existsIterator != data.m_itemNodeCache.end())
            {
                // This node is still in the model.
                (*existsIterator).second->active = true;
                // We need to recursively repopulate them to check if the childrean are still in the model and mark them
                // active/inactive.
                (*existsIterator).second->childrenPopulated = false;
                continue;
            }
        }
        else
        {
            // Trying to find out if we already have item. And instead of creating, we will reuse the old.
            auto oldNodeIterator = oldChildren.find(childItem.get());
            if (oldNodeIterator != oldChildren.end())
            {
                // Reuse
                result = std::move(oldNodeIterator->second);
                oldChildren.erase(oldNodeIterator);

                // It's here to repopulate children because we assume that if parent is changed, it's also possible
                // that children also changed. Example: the nodes was populated when filtering was enabled. When
                // filtering is disabled, it marks root needs to be updated. We need to repopulate the children of root
                // as well. That's why it's here. If there was no filtering, we would not need it.
                // TODO: Consider using additional flags for such corner cases.
                result->childrenPopulated = false;
            }
        }

        if (!result)
        {
            // Create new
            result = std::make_unique<Node>();
            result->item = childItem;
            result->level = node->level + 1;
            // See TreeView::_setNodeComputedHeight for details.
            result->nodeHeight = data.m_numHeights == 0 ? 0.f : data.m_sumHeights / data.m_numHeights;
            data.m_itemNodeCache.insert({ childItem.get(), result.get() });
        }

        // Check if this item should be selected
        auto selectionFoundIterrator = std::find(data.m_selection.begin(), data.m_selection.end(), childItem);
        result->selected = selectionFoundIterrator != data.m_selection.end();

        node->children.push_back(std::move(result));
    }

    // It's possible that the nodes that was selected was removed from the model. In this case we need to remove them
    // from m_selection.
    for (const auto& childItem : oldChildren)
    {
        std::deque<Node*> nodesToProcess;
        nodesToProcess.push_back(childItem.second.get());
        while (!nodesToProcess.empty())
        {
            auto* currentNode = nodesToProcess.front();
            nodesToProcess.pop_front();

            for (auto&& child : currentNode->children)
            {
                nodesToProcess.push_back(child.get());
            }

            const std::shared_ptr<const AbstractItemModel::AbstractItem>& item = currentNode->item;
            auto selectionFoundIterrator = std::find(data.m_selection.begin(), data.m_selection.end(), item);
            if (selectionFoundIterrator != data.m_selection.end())
            {
                data.m_selection.erase(selectionFoundIterrator);
            }

            data.m_itemNodeCache.erase(item.get());
        }
    }
}

void TreeView::_populateNodeChildrenRecursive(TreeView::Node* node)
{
    if (this->_isExpanded(node))
    {
        this->_populateNodeChildren(node);

        // Do the same for children if expanded.
        for (auto& child : node->children)
        {
            this->_populateNodeChildrenRecursive(child.get());
        }
    }
}

void TreeView::_populateNodeWidget(TreeView::Node* node)
{
    OMNIUI_PROFILE_VERBOSE_WIDGET_FUNCTION;
    if (node->widgetsPopulated)
    {
        return;
    }

    auto& data = _getData<TreeViewData>();
    const bool rootIsVisible = this->isRootVisible();

    if (!rootIsVisible && node == data.m_root.get())
    {
        return;
    }

    node->widgetsPopulated = true;
    node->widgetsDirty = false;

    // buildBranch and buildWidget called with this value, assert it is valid
    // (tjose calls are responsible for actually chekcing at runtime)
    //
    const auto& model = this->getModel();
    OMNIUI_ASSERT(model);

    float maxHeight = 0.0f;

    // Populate widgets
    node->widgets.clear();
    node->widgets.reserve(data.m_columnsCount);
    node->widgetsForInspector.clear();
    node->widgetsForInspector.reserve(data.m_columnsCount);
    for (size_t i = 0; i < data.m_columnsCount; ++i)
    {
        // To make the inspector working we save the key widgets that contain
        // the user branch and the user widget created by the delegate.
        std::pair<std::shared_ptr<Widget>, std::shared_ptr<Widget>> widgetForInspector;

        // It has the following layout per cell:
        // +--------+--------+
        // | branch | widget |
        // +--------+--------+
        // The delegate can skip anything. We assign the mouse event to expand and collapse node to the branch frame so
        // the user shouldn't worry about it.
        // TODO: Still WIP. Should we take the indenatation from the style instead? In this way how to specify which
        // column should have the indentation?
        // TODO: Still WIP. Do we need to have two functions per cell? If no, how delegate can open/close the node?
        // If delegate can access TreeView, it is a circular dependency which is unacceptable. Also in the future we
        // will be able to use branch to draw lines from parent to child.
        std::shared_ptr<HStack> stack;
        OMNIKIT_WITH_CONTAINER(nullptr)
        {
            stack = HStack::create();
            stack->setWidth(Pixel(0.0f));
            stack->setHeight(Pixel(0.0f));
            stack->setScale(this->_getScale());
        }

        OMNIKIT_WITH_CONTAINER(stack)
        {
            // The branch part from the delegate
            auto branchStack = VStack::create();
            // The branch should be aligned to the left side
            branchStack->setWidth(Pixel(0.0f));
            OMNIKIT_WITH_CONTAINER(branchStack)
            {
                Spacer::create();

                auto zstack = ZStack::create();
                zstack->setHeight(Pixel(0.0f));
                OMNIKIT_WITH_CONTAINER(zstack)
                {
                    this->getDelegate()->buildBranch(
                        model, node->item, i, node->level - (1u - rootIsVisible), this->_isExpanded(node));

                    // Expand/collapse button. Since it's zstack, this button will have the same size as the
                    // user defined branch.
                    auto button = InvisibleButton::create();
                    button->useMarginFromStyle(false);
                    button->setClickedFn(
                        [node, this]()
                        {
                            if (this->isExpandOnBranchClick())
                            {
                                const auto& io = ImGui::GetIO();
                                // Expand all if Shift
                                this->_setExpanded(node, !node->expanded, io.KeyShift);
                            }
                        });
                }

                widgetForInspector.first = zstack;

                Spacer::create();
            }

            // The widget from the delegate
            OMNIKIT_WITH_CONTAINER(VStack::create())
            {
                Spacer::create();
                auto frame = Frame::create();
                frame->setHeight(Pixel(0.0f));
                OMNIKIT_WITH_CONTAINER(frame)
                {
                    this->getDelegate()->buildWidget(
                        model, node->item, i, node->level, this->_isExpanded(node));
                }
                Spacer::create();

                widgetForInspector.second = frame;
            }
        }

        // Precompute the width of the widget.
        stack->setParent(this);
        stack->setSelected(node->selected);
        stack->setComputedWidth(data.m_columnComputedSizes[i]);
        stack->setComputedHeight(maxHeight);

        maxHeight = std::max(maxHeight, stack->getComputedHeight());

        // Save the widget in our datastruct to reuse it in the future
        node->widgets.push_back(stack);
        node->widgetsForInspector.push_back(std::move(widgetForInspector));
    }

    // Set the height of the widgets that are not equal to the max height. It prevents from blinking.
    for (const auto& widget : node->widgets)
    {
        float currentHeight = widget->getComputedHeight();
        if (currentHeight != maxHeight)
        {
            widget->setComputedHeight(maxHeight);
        }
    }

    node->nodeHeight = maxHeight;
    node->heightComputed = true;
    data.m_sumHeights += maxHeight;
    data.m_numHeights++;
}

void TreeView::_populateNodeWidgetsRecursive(TreeView::Node* node)
{
    this->_populateNodeWidget(node);

    if (this->_isExpanded(node))
    {
        // Do the same for children if expanded.
        for (auto& child : node->children)
        {
            this->_populateNodeWidgetsRecursive(child.get());
        }
    }
}

void TreeView::_populateHeader()
{
    OMNIUI_PROFILE_VERBOSE_WIDGET_FUNCTION;
    auto& data = _getData<TreeViewData>();
    if (!this->isHeaderVisible() || data.m_headerPopulated)
    {
        return;
    }

    data.m_headerPopulated = true;

    const auto& delegate = this->getDelegate();

    data.m_headerWidgets.clear();
    data.m_headerWidgets.reserve(data.m_columnsCount);
    OMNIKIT_WITH_CONTAINER(nullptr)
    {
        for (size_t i = 0; i < data.m_columnsCount; ++i)
        {
            auto frame = Frame::create();
            frame->setParent(this);
            frame->setScale(this->_getScale());
            data.m_headerWidgets.push_back(frame);

            OMNIKIT_WITH_CONTAINER(frame)
            {
                auto stack = ZStack::create();
                stack->setContentClipping(true);
                OMNIKIT_WITH_CONTAINER(stack)
                {
                    // Background
                    auto background = Rectangle::create();
                    background->setStyleTypeNameOverride("TreeView.Header");
                    background->setName("background");

                    delegate->buildHeader(i);
                }
            }
        }
    }
}

void TreeView::_setHeaderComputedWidth()
{
    if (!this->isHeaderVisible())
    {
        return;
    }

    auto& data = _getData<TreeViewData>();
    OMNIUI_ASSERT(data.m_columnComputedSizes.size() == data.m_headerWidgets.size());

    for (size_t i = 0, n = data.m_headerWidgets.size(); i < n; ++i)
    {
        data.m_headerWidgets[i]->forceWidthDirty(SizeDirtyReason::eParentDirty);
        data.m_headerWidgets[i]->setComputedWidth(data.m_columnComputedSizes[i]);
    }
}

void TreeView::_setHeaderComputedHeight(float& headerHeight)
{
    if (!this->isHeaderVisible())
    {
        return;
    }

    auto& data = _getData<TreeViewData>();

    // Set 0 to determine the minimal possible size.
    for (const auto& header : data.m_headerWidgets)
    {
        header->setComputedHeight(0.0f);
    }

    // Get max
    float maxHeight = 0.0f;
    for (const auto& header : data.m_headerWidgets)
    {
        maxHeight = std::max(maxHeight, header->getComputedHeight());
    }

    // Set the same max to all
    for (const auto& header : data.m_headerWidgets)
    {
        header->setComputedHeight(maxHeight);
    }

    headerHeight = maxHeight;
}

float TreeView::_drawNodeInTable(const std::unique_ptr<TreeView::Node>& node,
                                 const std::unique_ptr<TreeView::Node>& parent,
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
                                 float elapsedTime)
{
    OMNIUI_PROFILE_VERBOSE_WIDGET_FUNCTION;
    if (this->isKeepAlive() && !node->active)
    {
        return 0.0f;
    }

    auto& data = _getData<TreeViewData>();

    // Lazy-population. Populate node with children and widgets if not populated.
    if (currentOffset <= data.m_relativeRectMax && data.m_relativeRectMin <= currentOffset + node->nodeHeight)
    {
        this->_populateNodeWidget(node.get());
    }

    // True if this item is visible in the scrolling frame
    bool visible;
    float nodeHeight;

    if (!this->isRootVisible() && node == data.m_root)
    {
        // Do nothing and draw nothing.
        nodeHeight = 0.0f;
        visible = false;
    }
    else
    {
        // Use saved size
        nodeHeight = node->nodeHeight;

        // Check visibility using only heights.
        visible =
            nodeHeight > 0.0f && currentOffset <= data.m_relativeRectMax && data.m_relativeRectMin <= currentOffset + nodeHeight;

        if (visible)
        {
            ImGui::PushID(node.get());

            ImVec2 nodeCursor{ cursorAtBeginTableX, cursorAtBeginTableY + currentOffset };
            ImVec2 nodeSize{ data.m_contentWidth, nodeHeight };
            ImVec2 nodeRectMax{ nodeCursor.x + nodeSize.x, nodeCursor.y + nodeSize.y };

            // Flag if the mouse hovers the node area
            bool hoveredBelow = false;
            bool hovered = !blockMouse && ImGui::IsMouseHoveringRect(nodeCursor, nodeRectMax);
            bool hoveredAbove = false;

            if (this->hasHoverChangedFn() && node->hovered != hovered)
            {
                this->callHoverChangedFn(node->item, hovered);
            }
            node->hovered = hovered;

            if (parent && this->isDropBetweenItems())
            {
                // We need to check below and above areas only if this mode is enabled.
                constexpr float threshold = 0.25f;
                ImVec2 nodeBeforeAreaRectMax{ nodeRectMax.x, nodeCursor.y + nodeSize.y * threshold };
                ImVec2 nodeAfterAreaRectMin{ nodeCursor.x, nodeCursor.y + nodeSize.y * (1.0f - threshold) };
                hoveredBelow = !blockMouse && ImGui::IsMouseHoveringRect(nodeCursor, nodeBeforeAreaRectMax);
                hoveredAbove = !blockMouse && ImGui::IsMouseHoveringRect(nodeAfterAreaRectMin, nodeRectMax);
            }

            // Check if the node accepts drops depending on the area the mouse hovers.
            bool needDragDropHighlightBelow = false;
            bool needDragDropHighlight = false;
            bool needDragDropHighlightAbove = false;

            if (hoveredBelow)
            {
                needDragDropHighlightBelow = this->_hasAcceptedDrop(node, parent, DropLocation::eBelow);
            }
            else if (hoveredAbove)
            {
                needDragDropHighlightAbove = this->_hasAcceptedDrop(node, parent, DropLocation::eAbove);
            }
            else if (hovered)
            {
                needDragDropHighlight = this->_hasAcceptedDrop(node, parent, DropLocation::eOver);
            }

            bool isDragDrop = needDragDropHighlightBelow || needDragDropHighlightAbove || needDragDropHighlight;
            bool needToDrawBorder = isDragDrop || (hovered && hoveringBorderColor != 0);
            auto drawList = ImGui::GetWindowDrawList();

            // Draw background states or widgets if it has no hovering or drop borders.
            auto widgetCursor = nodeCursor;
            for (size_t i = 0, n = node->widgets.size(); i < data.m_columnsCount && i < n; ++i)
            {
                ImGui::SetCursorScreenPos(widgetCursor);

                const auto& widget = node->widgets[i];
                float columnWidth = data.m_columnComputedSizes[i];

                ImVec2 widgetRectMax{ widgetCursor.x + columnWidth, widgetCursor.y + nodeHeight };
                drawList->PushClipRect(ImFloor(widgetCursor), ImFloor(widgetRectMax), true);

                if (node->selected)
                {
                    // Draw selection highlight in the background
                    drawList->AddRectFilled(widgetCursor, widgetRectMax, backgroundColor, 0.0f);
                }

                if (isDragDrop)
                {
                    ImVec2 rectStart;
                    ImVec2 rectMax;
                    if (needDragDropHighlightBelow)
                    {
                        rectStart = nodeCursor;
                        rectMax = ImVec2(nodeRectMax.x, nodeCursor.y + dropIndicatorThickness);
                    }
                    else if (needDragDropHighlightAbove)
                    {
                        rectStart = ImVec2(nodeCursor.x, nodeRectMax.y - dropIndicatorThickness);
                        rectMax = nodeRectMax;
                    }
                    else
                    {
                        rectStart = nodeCursor;
                        rectMax = nodeRectMax;
                    }

                    // To keep consistent of default style before so it will only draw
                    // border if backgroundColor for drop is not provided.
                    if (dropIndicatorColor != 0)
                    {
                        drawList->AddRectFilled(rectStart, rectMax, dropIndicatorColor);
                    }
                }
                else if (!node->selected && hovered && ImGui::IsWindowHovered(ImGuiHoveredFlags_ChildWindows))
                {
                    // Draw the mouse hovering rectangle. IsWindowHovered is to prevent the highlight when the mouse is
                    // under the item, but another window blocks it.
                    //
                    // OVUI_REFERENCE_IMPLEMENTATION_PLAN Step 3.3 / UI-006 (correction 2):
                    // Skip the hover background paint when the node is already
                    // selected. The selection paint at line 1561-1565 above
                    // is opaque, so without this guard the hover rectangle
                    // would overpaint the selection fill on a hovered+selected
                    // row, making the row read as hover (#1F1F1F) instead of
                    // selected (#363636). Codex correction-2 review on commit
                    // f000512 caught this: selected dominance must hold over
                    // hover. Drag-drop indicators above and the focus border
                    // below remain unaffected — they paint independently in
                    // their own branches.
                    drawList->AddRectFilled(widgetCursor, widgetRectMax, hoveringColor, 0.0f);
                }
                else
                {
                    if (node->dragEntered != DropLocation::eUndefined)
                    {
                        // Reset DnD flag to be able to know when the mouse returns to this item.
                        node->dragEntered = DropLocation::eUndefined;
                    }
                }

                // We don't need to draw border.
                if (!needToDrawBorder)
                {
                    widget->draw(elapsedTime);
                }

                drawList->PopClipRect();

                widgetCursor.x += columnWidth;
            }

            if (needToDrawBorder)
            {
                // Draw border to the whole node instead of single widget.
                ImGui::SetCursorScreenPos(nodeCursor);
                drawList->PushClipRect(ImFloor(nodeCursor), ImFloor(nodeRectMax), true);

                ImVec2 borderRectStart = nodeCursor;
                ImVec2 borderRectMax = nodeRectMax;
                if (isDragDrop)
                {
                    if (needDragDropHighlightBelow)
                    {
                        borderRectMax = ImVec2(nodeRectMax.x, nodeCursor.y + dropIndicatorThickness);
                    }
                    else if (needDragDropHighlightAbove)
                    {
                        borderRectStart = ImVec2(nodeCursor.x, nodeRectMax.y - dropIndicatorThickness);
                    }
                }

                uint32_t borderColor = isDragDrop ? dropIndicatorBorderColor : hoveringBorderColor;
                drawList->AddRect(
                    borderRectStart, borderRectMax, borderColor, 0.0, ImDrawFlags_RoundCornersAll, dropIndicatorThickness);

                drawList->PopClipRect();

                // Lastly, we draw widgets if it needs to draw hovering or drop borders to put widgets on top.
                widgetCursor = nodeCursor;
                for (size_t i = 0, n = node->widgets.size(); i < data.m_columnsCount && i < n; ++i)
                {
                    ImGui::SetCursorScreenPos(widgetCursor);

                    const auto& widget = node->widgets[i];
                    float columnWidth = data.m_columnComputedSizes[i];

                    ImVec2 widgetRectMax{ widgetCursor.x + columnWidth, widgetCursor.y + nodeHeight };
                    drawList->PushClipRect(ImFloor(widgetCursor), ImFloor(widgetRectMax), true);

                    widget->draw(elapsedTime);

                    drawList->PopClipRect();

                    widgetCursor.x += columnWidth;
                }
            }

            // Selection button
            ImGui::SetCursorScreenPos(nodeCursor);
            if (data.m_resizeColumn == 0 && nodeSize.y > 0.0f && ImGui::InvisibleButton("##selection", nodeSize))
            {
                const ImGuiIO& io = ImGui::GetIO();
                if (io.KeyCtrl)
                {
                    this->_toggleSelection(node->item);
                }
                else if (io.KeyShift)
                {
                    this->_extendSelection(node->item);
                }
                else
                {
                    this->_setSelection({ node->item });
                }
            }

            // m_resizeColumn == 0 means no column is resizing at this moment
            if (data.m_resizeColumn == 0 && ImGui::BeginDragDropSource(ImGuiDragDropFlags_None))
            {
                if (!node->dragInProgress)
                {
                    // We are here because the user started dragging the object.
                    this->_beginDrag(node.get());
                }

                if (data.m_dragAndDropPayloadBuffer)
                {
                    // Data for drag
                    ImGui::SetDragDropPayload(Widget::getDragDropPayloadId(), data.m_dragAndDropPayloadBuffer.get(),
                                              data.m_dragAndDropPayloadBufferSize);

                    this->_drawDrag(elapsedTime, backgroundColor);
                }

                ImGui::EndDragDropSource();
            }
            else if (node->dragInProgress)
            {
                node->dragInProgress = false;
            }

            if (node->dropAccepted)
            {
                // Drop
                this->_dragDropTarget(node.get(), parent.get());
            }

            ImGui::PopID();
        }
    }

    if (visible)
    {
        // Recomputing the widget size takes a very long time if we have thousands of items. To be in a reasonable time,
        // we don't do it every frame. We compute it when the size is changed and if the item is visible on the screen.
        // We assume that other widgets always have a fixed size.
        node->widthComputed = false;
        node->heightComputed = false;
        if (node->widgetsDirty)
        {
            node->widgetsPopulated = false;
        }
    }

    if (data.m_scrollHere && node.get() == data.m_scrollHere)
    {
        if (visible)
        {
            // We don't need to scroll here if the node is alredy visible.
            data.m_scrollHere = nullptr;
        }
        else
        {
            auto* ctx = ImGui::GetCurrentContext();
            ImGuiWindow* window = ctx->CurrentWindow;

            // We can't use ImGui::SetScrollHereY() because it has precision issues when the tree view is big.
            // The following code is similar to ImGui::SetScrollY().

            // Window space
            float targetY = cursorAtBeginTableY + currentOffset - window->Pos.y;
            ImGui::SetScrollFromPosY(window, targetY, 0.5f);
        }
    }

    if (this->_isExpanded(node.get()))
    {
        this->_populateNodeChildren(node.get());

        // Draw children if expanded.
        for (auto& child : node->children)
        {
            float childOffset = currentOffset + nodeHeight;
            if (!data.m_scrollHere && childOffset > data.m_relativeRectMax)
            {
                // Skip the rest
                break;
            }

            nodeHeight += this->_drawNodeInTable(child, node, hoveringColor, hoveringBorderColor, backgroundColor, dropIndicatorColor,
                                                 dropIndicatorBorderColor, dropIndicatorThickness, cursorAtBeginTableX,
                                                 cursorAtBeginTableY, childOffset, blockMouse, elapsedTime);
        }
    }

    return nodeHeight;
}

void TreeView::_setNodeComputedWidth(const std::unique_ptr<Node>& node)
{
    OMNIUI_PROFILE_VERBOSE_WIDGET_FUNCTION;

    auto& data = _getData<TreeViewData>();
    OMNIUI_ASSERT(data.m_columnComputedSizes.size() == data.m_columnsCount);

    if (this->isKeepAlive() && !node->active)
    {
        return;
    }

    if (!node->widthComputed || data.m_contentWidthDirty)
    {
        for (size_t i = 0, n = std::min(data.m_columnsCount, node->widgets.size()); i < n; ++i)
        {
            auto& currentWidget = node->widgets[i];
            currentWidget->forceWidthDirty(SizeDirtyReason::eParentDirty);
            currentWidget->setComputedWidth(data.m_columnComputedSizes[i]);
        }

        node->widthComputed = true;
    }

    if (this->_isExpanded(node.get()))
    {
        for (const auto& child : node->children)
        {
            if (child->positionOffset > data.m_relativeRectMax)
            {
                break;
            }

            this->_setNodeComputedWidth(child);
        }
    }
}

bool TreeView::_setNodeComputedHeight(const std::unique_ptr<Node>& node, float& offset)
{
    OMNIUI_PROFILE_VERBOSE_WIDGET_FUNCTION;
    if (this->isKeepAlive() && !node->active)
    {
        return true;
    }

    auto& data = _getData<TreeViewData>();
    bool rootIsVisible = this->isRootVisible();
    bool nodeVisible = rootIsVisible || node != data.m_root;
    if (nodeVisible)
    {
        // TODO: Evaluate if we can get rid of this.
        // We set node->nodeHeight in TreeView::_populateNodeWidget when the widget is created and in
        // TreeView::_populateNodeChildren and when the node is created in TreeView::_populateNodeChildren. This block
        // is only executed if the size of TreeView is changing.
        if (!node->heightComputed)
        {
            if (!node->widgetsPopulated && node->widgets.empty())
            {
                // The widget was never created. But we need to know its height because we need to know the full
                // height of the widget. We assume that the height is an average height. In 99% of cases it works,
                // and the total width will be corrected once user scrolls to the widget.
                node->nodeHeight = data.m_numHeights == 0 ? 0.f : data.m_sumHeights / data.m_numHeights;
            }
            else
            {
                // First get the max height.
                float maxHeight = 0.0f;
                for (const auto& widget : node->widgets)
                {
                    widget->setComputedHeight(0.0f);
                    maxHeight = std::max(maxHeight, widget->getComputedHeight());
                }

                // Sets the same height to all of them.
                for (const auto& widget : node->widgets)
                {
                    if (widget->getComputedHeight() < maxHeight)
                    {
                        widget->setComputedHeight(maxHeight);
                    }
                }

                node->nodeHeight = maxHeight;
                node->heightComputed = true;
            }
        }

        node->positionOffset = offset;
        offset += node->nodeHeight;
    }

    if (this->_isExpanded(node.get()))
    {
        for (const auto& child : node->children)
        {
            if (!data.m_contentHeightDirty && offset == child->positionOffset && offset > data.m_relativeRectMax)
            {
                // If the full height is not dirty, skip the rest.
                return false;
            }

            if (!this->_setNodeComputedHeight(child, offset))
            {
                return false;
            }
        }
    }

    return true;
}

float TreeView::_computeColumnWidths(float width)
{
    OMNIUI_PROFILE_VERBOSE_WIDGET_FUNCTION;

    auto& data = _getData<TreeViewData>();

    // Compute the size of columns
    // TODO: We will get rid of dpiScale soon
    // TODO: This method is very similar to Stack::_evaluateConsecutiveLayout. We need to share the code.
    float dpiScale = this->getDpiScale();

    auto columnWidths = this->getColumnWidths();
    const auto& minColumnWidths = this->getMinColumnWidths();
    float lengthForFractions = width;
    float totalWidthComputed = 0.0f;
    float totalFractions = 0.0f;

    OMNIUI_ASSERT(data.m_columnComputedSizes.size() == data.m_columnsCount);
    OMNIUI_ASSERT(data.m_minColumnComputedSizes.size() == data.m_columnsCount);

    for (size_t i = 0; i < data.m_columnsCount; ++i)
    {
        const auto minColumnWidth = i < minColumnWidths.size() ? minColumnWidths[i] : Pixel(0);

        float computedMinWidth = 0.0;
        if (minColumnWidth.unit == UnitType::ePixel)
        {
            computedMinWidth = minColumnWidth.value * dpiScale;
        }
        else if (minColumnWidth.unit == UnitType::ePercent)
        {
            computedMinWidth = minColumnWidth.value * 1e-2f * width;
        }

        data.m_minColumnComputedSizes[i] = computedMinWidth;
    }

    // Apply cached desired width for the last column if available (measured during draw)
    if (data.m_columnsCount >= 1)
    {
        if (data.m_lastColumnMeasuredMinPx > 0.0f)
        {
            const size_t lastCol = data.m_columnsCount - 1;
            data.m_minColumnComputedSizes[lastCol] = std::max(data.m_minColumnComputedSizes[lastCol], data.m_lastColumnMeasuredMinPx);
        }
    }

    // Compute Pixels and Percents. They don't depend on the length of others so they can be computed right away.
    bool columnWidthChanged = false;
    for (size_t i = 0; i < data.m_columnsCount; ++i)
    {
        const auto columnWidth = i < columnWidths.size() ? columnWidths[i] : Fraction(1);
        float minColumnWidth = data.m_minColumnComputedSizes[i];

        float computedWidth;
        if (columnWidth.unit == UnitType::ePixel)
        {
            computedWidth = columnWidth.value * dpiScale;
            if (computedWidth < minColumnWidth && i < columnWidths.size())
            {
                columnWidthChanged = true;
                columnWidths[i].value = minColumnWidth;
            }
        }
        else if (columnWidth.unit == UnitType::ePercent)
        {
            computedWidth = columnWidth.value * 1e-2f * width;
            if (computedWidth < minColumnWidth && i < columnWidths.size())
            {
                columnWidthChanged = true;
                columnWidths[i].value = minColumnWidth / width;
            }
        }
        else // if (columnWidth.unit == UnitType::eFraction)
        {
            totalFractions += columnWidth.value;
            // If it's Fraction, we will set it on the second pass.
            continue;
        }

        computedWidth = std::max(computedWidth, minColumnWidth);
        data.m_columnComputedSizes[i] = computedWidth;

        lengthForFractions -= computedWidth;
        totalWidthComputed += computedWidth;
    }

    // Compute Fractions
    if (lengthForFractions > 0.0f)
    {
        for (size_t i = 0; i < data.m_columnsCount; ++i)
        {
            const auto columnWidth = i < columnWidths.size() ? columnWidths[i] : Fraction(1);

            if (columnWidth.unit == UnitType::ePixel)
            {
                continue;
            }
            else if (columnWidth.unit == UnitType::ePercent)
            {
                continue;
            }
            // else if (columnWidth.unit == UnitType::eFraction)

            // Set the lengths of the Fraction units.
            float computedWidth = totalFractions == 0.0f ? 0.0f : columnWidth.value * lengthForFractions / totalFractions;
            float minColumnWidth = data.m_minColumnComputedSizes[i];
            if (computedWidth < minColumnWidth && i < columnWidths.size())
            {
                columnWidthChanged = true;
                columnWidths[i].value = minColumnWidth / lengthForFractions;
            }

            computedWidth = std::max(computedWidth, minColumnWidth);
            data.m_columnComputedSizes[i] = computedWidth;

            lengthForFractions -= computedWidth;
            totalFractions -= columnWidth.value;

            totalWidthComputed += computedWidth;
        }
    }

    if (columnWidthChanged)
    {
        this->setColumnWidths(columnWidths);
    }

    return totalWidthComputed;
}

TreeView::Node* TreeView::_getNode(const std::unique_ptr<TreeView::Node>& node,
                                   const std::shared_ptr<const AbstractItemModel::AbstractItem>& item) const
{
    // Iterate all the nodes and find the one with requested AbstractItemModel
    // TODO: It can be slow in some cases. We need to optimize it.

    // Check the given node first
    if (node->item == item)
    {
        return node.get();
    }

    // Recursively check the children
    auto& data = _getData<TreeViewData>();
    auto iter = data.m_itemNodeCache.find(item.get());
    if (iter != data.m_itemNodeCache.end())
    {
        return iter->second;
    }

    // Nothing is found
    return nullptr;
}

TreeView::Node* TreeView::_getNode(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item) const
{
    auto& data = _getData<TreeViewData>();
    if (item == nullptr)
    {
        return data.m_root.get();
    }
    return _getNode(data.m_root, item);
}

void TreeView::_createFlatNodeList(std::unique_ptr<TreeView::Node>& node, std::vector<std::unique_ptr<Node>*>& list) const
{
    list.push_back(&node);

    if (this->_isExpanded(node.get()))
    {
        for (auto& child : node->children)
        {
            This::_createFlatNodeList(child, list);
        }
    }
}

void TreeView::_clearNodeSelection(std::unique_ptr<TreeView::Node>& node)
{
    if (node->selected)
    {
        node->selected = false;

        for (auto& widget : node->widgets)
        {
            if (widget)
            {
                widget->setSelected(false);
            }
        }
    }

    for (auto& child : node->children)
    {
        This::_clearNodeSelection(child);
    }
}

void TreeView::_onSelectionChanged()
{
    this->callSelectionChangedFn(this->getSelection());
    _getData<TreeViewData>().m_contentHeightDirty = true;
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

bool TreeView::_hasAcceptedDrop(const std::unique_ptr<TreeView::Node>& node,
                                const std::unique_ptr<TreeView::Node>& parent,
                                DropLocation dropLocation) const
{
    const ImGuiPayload* payload = ImGui::GetDragDropPayload();
    if (!payload)
    {
        return false;
    }

    const TreeView::Node* dropNode = nullptr;
    int32_t dropId;
    TreeView::_getDropNode(node.get(), parent.get(), dropLocation, &dropNode, dropId);
    OMNIUI_ASSERT(dropNode);

    auto& data = _getData<TreeViewData>();

    // The item to pass to the model considering the fact that if it's root, we need to pass None.
    const std::shared_ptr<const AbstractItemModel::AbstractItem>& dropItem =
        dropNode == data.m_root.get() ? nullptr : node->item;

    if (payload->IsDataType(Widget::getDragDropPayloadId()))
    {
        // TODO: Draw the beautiful drag icon instead of the ugly one in BeginDragDropSource

        if (node->dragEntered != dropLocation)
        {
            node->dragEntered = dropLocation;
            const auto& model = this->getModel();
            OMNIUI_ASSERT(model);

            auto items = this->_payloadToItems(payload);
            if (items.empty())
            {
                const char* sourceAsset = reinterpret_cast<const char*>(payload->Data);
                node->dropAccepted = model->dropAccepted(dropItem, sourceAsset, dropId);
            }
            else
            {
                node->dropAccepted = true;

                for (auto sourceItem : items)
                {
                    bool currentlyAccepted = model->dropAccepted(dropItem, sourceItem, dropId);
                    if (!currentlyAccepted)
                    {
                        // We need the model to accept all the drops to proceed.
                        node->dropAccepted = false;
                        break;
                    }
                }
            }
        }
    }
    else if (payload->IsDataType(g_contentDropType))
    {
        // Drag and drop from the Context Browser
        if (node->dragEntered != dropLocation)
        {
            const char* sourceAsset = reinterpret_cast<const char*>(payload->Data);

            node->dragEntered = dropLocation;
            const auto& model = this->getModel();
            OMNIUI_ASSERT(model);
            node->dropAccepted = model->dropAccepted(dropItem, sourceAsset, dropId);
        }
    }
    else if (node->dropAccepted)
    {
        node->dropAccepted = false;
    }

    if (!node->dropAccepted)
    {
        return false;
    }

    return true;
}

void TreeView::_getDropNode(const TreeView::Node* node,
                            const TreeView::Node* parent,
                            DropLocation dropLocation,
                            TreeView::Node const** dropNode,
                            int32_t& dropId)
{
    if (dropLocation == DropLocation::eAbove && node->expanded)
    {
        // Special case: drop right after expanded node.
        *dropNode = node;
        dropId = 0;
    }
    else if (!parent || dropLocation == DropLocation::eOver)
    {
        // Drop on the node.
        *dropNode = node;
        dropId = -1;
    }
    else
    {
        // Drop between nodes. We have to have a parent with children.
        OMNIUI_ASSERT(parent);
        *dropNode = parent;

        // Get the ID of the node in its parent
        OMNIUI_ASSERT(!parent->children.empty());
        auto nodeIterator = std::find_if(
            parent->children.begin(), parent->children.end(), [&node](const auto& it) { return it.get() == node; });
        size_t id = std::distance(parent->children.begin(), nodeIterator);

        if (dropLocation == DropLocation::eAbove)
        {
            dropId = static_cast<uint32_t>(id) + 1;
        }
        else // DropLocation::eBelow
        {
            dropId = static_cast<uint32_t>(id);
        }
    }
}

void TreeView::_setExpanded(TreeView::Node* node, bool expanded, bool recursive, bool pouplateChildren)
{
    node->expanded = expanded;
    this->_setWidgetsDirty(node, true, false);

    if (pouplateChildren)
    {
        this->_populateNodeChildren(node);
    }

    if (recursive)
    {
        for (auto& child : node->children)
        {
            this->_setExpanded(child.get(), expanded, recursive, pouplateChildren);
        }
    }

    auto& data = _getData<TreeViewData>();
    data.m_contentHeightDirty = true;

    if (node == data.m_root.get())
    {
        this->setRootExpanded(expanded);
    }
}

bool TreeView::_isExpanded(TreeView::Node* node) const
{
    return node->expanded || this->isKeepExpanded();
}

void TreeView::_setWidgetsDirty(TreeView::Node* node, bool dirty, bool recursive) const
{
    node->widgetsDirty = dirty;

    if (recursive)
    {
        for (auto& child : node->children)
        {
            this->_setWidgetsDirty(child.get(), dirty, recursive);
        }
    }
}

void TreeView::_beginDrag(TreeView::Node* node)
{
    auto& data = _getData<TreeViewData>();

    // If the selection doesn't contain the node we drag, we should clear the selection and select the node.
    auto found = std::find(data.m_selection.begin(), data.m_selection.end(), node->item);
    if (found == data.m_selection.end())
    {
        this->_setSelection({ node->item });
    }

    size_t selectionSize = data.m_selection.size();

    // Keep the nodes the user is dragging to draw them in _drawDrag.
    data.m_dragAndDropNodes.clear();
    data.m_dragAndDropNodes.reserve(selectionSize);
    if (selectionSize == 1)
    {
        // Shortcut for the most common case.
        data.m_dragAndDropNodes.push_back(node);
    }
    else
    {
        for (const auto& item : data.m_selection)
        {
            Node* foundNode = this->_getNode(item);
            if (!foundNode)
            {
                continue;
            }

            data.m_dragAndDropNodes.push_back(foundNode);
        }
    }

    // Pack string with mime data and the pointer to the item to one single buffer to send it to ImGui.
    const auto& model = this->getModel();
    OMNIUI_ASSERT(model);

    const std::string mimeString = model->getDragMimeData(node->item);
    const size_t mimeDataSize = mimeString.size() + 1; // Add 1 for c-string/data trailing '\0'
    if (mimeDataSize > 1)
    {
        // FIXME: This is writing raw pointers to possibly un-aligned memory, as well as storing them
        // without any reference counting (m_selection is a vector of shared pointer, serialized with m_selection[i].get())
        //

        // Size of Mime data + size of pointer to the item
        data.m_dragAndDropPayloadBufferSize = mimeDataSize + (sizeof(AbstractItemModel::AbstractItem*) * selectionSize);

        data.m_dragAndDropPayloadBuffer = std::make_unique<char[]>(data.m_dragAndDropPayloadBufferSize);
        memcpy(data.m_dragAndDropPayloadBuffer.get(), mimeString.c_str(), mimeDataSize);
        // Should have copied a trailing '\0'
        OMNIUI_ASSERT(data.m_dragAndDropPayloadBuffer.get()[mimeDataSize - 1] == 0);

        // Fill the rest of the memory with the pointers to the items
        auto target =
            reinterpret_cast<AbstractItemModel::AbstractItem const**>(data.m_dragAndDropPayloadBuffer.get() + mimeDataSize);
        for (size_t i = 0; i < selectionSize; ++i)
        {
            target[i] = data.m_selection[i].get();
        }
    }

    node->dragInProgress = true;
}

void TreeView::_drawDrag(float elapsedTime, uint32_t backgroundColor) const
{
    auto& data = _getData<TreeViewData>();
    if (data.m_dragAndDropNodes.empty())
    {
        return;
    }

    auto drawList = ImGui::GetWindowDrawList();

    // The drag and drop window is transparent, so we need to draw the selection rect transparent as well.
    // For now alpha is 1/2 of the original background aloha.
    // TODO: Get transparency of this from style.
    uint32_t alpha = ((backgroundColor >> 24) / 2) << 24;
    uint32_t transparentBackground = alpha | (0x00ffffff & backgroundColor);

    auto cursor = ImGui::GetCursorScreenPos();
    for (const auto* node : data.m_dragAndDropNodes)
    {
        ImGui::SetCursorScreenPos(cursor);

        if (node->widgets.empty())
        {
            continue;
        }

        const auto& widget = node->widgets.front();
        if (!widget)
        {
            continue;
        }

        if (node->selected)
        {
            // Draw selection highlight in the background
            ImVec2 widgetRectMax{ cursor.x + widget->getComputedWidth(), cursor.y + widget->getComputedHeight() };
            drawList->AddRectFilled(cursor, widgetRectMax, transparentBackground, 0.0f);
        }

        widget->draw(elapsedTime);
        cursor.y += widget->getComputedHeight();
    }
}

void TreeView::_endDrag() const
{
    auto& data = _getData<TreeViewData>();
    data.m_dragAndDropPayloadBuffer.reset();
    data.m_dragAndDropPayloadBufferSize = 0;
    data.m_dragAndDropNodes.clear();
}

void TreeView::_dragDropTarget(TreeView::Node* node, TreeView::Node* parent) const
{
    ImGui::PushStyleColor(ImGuiCol_DragDropTarget, 0x0);

    if (ImGui::BeginDragDropTarget())
    {
        const TreeView::Node* dropNode = nullptr;
        int32_t dropId;
        TreeView::_getDropNode(node, parent, node->dragEntered, &dropNode, dropId);
        OMNIUI_ASSERT(dropNode);

        auto& data = _getData<TreeViewData>();

        // The item to pass to the model considering the fact that if it's root, we need to pass None.
        const std::shared_ptr<const AbstractItemModel::AbstractItem>& dropItem =
            dropNode == data.m_root.get() ? nullptr : node->item;

        if (const ImGuiPayload* payload = ImGui::AcceptDragDropPayload(Widget::getDragDropPayloadId()))
        {
            auto items = this->_payloadToItems(payload);
            if (items.empty())
            {
                const char* sourceAsset = reinterpret_cast<const char*>(payload->Data);
                this->getModel()->drop(dropItem, sourceAsset, dropId);
            }
            else
            {
                // Sent the drop notification to the model.
                for (auto sourceItem : this->_payloadToItems(payload))
                {
                    this->getModel()->drop(dropItem, sourceItem, dropId);
                }
            }
        }
        else if (const ImGuiPayload* payload = ImGui::AcceptDragDropPayload(g_contentDropType))
        {
            // Sent the drop notification to the model.
            auto source = reinterpret_cast<const char*>(payload->Data);
            this->getModel()->drop(dropItem, source, dropId);
        }
        ImGui::EndDragDropTarget();
    }

    ImGui::PopStyleColor();
}

std::vector<std::shared_ptr<Widget>> TreeView::_getChildren()
{
    // Populate header
    this->_populateHeader();

    auto& data = _getData<TreeViewData>();

    // Populate the internal state
    this->_populateNodeChildrenRecursive(data.m_root.get());
    // Populate all the widgets
    this->_populateNodeWidgetsRecursive(data.m_root.get());

    // Form list of headers, branches, widgets
    std::vector<std::shared_ptr<Widget>> result;

    // Count the number of visible nodes to reserve
    size_t nodesCount = 0;
    std::function<void(TreeView::Node*)> countRecursive;
    countRecursive = [&nodesCount, &countRecursive, this](TreeView::Node* node) {
        nodesCount++;
        if (this->_isExpanded(node))
        {
            // Do the same for children if expanded.
            for (auto& child : node->children)
            {
                countRecursive(child.get());
            }
        }
    };

    // `nodesCount * 2` is because we have a branch and a widget
    // 1 stands for the headers
    result.reserve(data.m_columnsCount * (nodesCount * 2 + 1));

    // Headers
    if (this->isHeaderVisible())
    {
        OMNIUI_ASSERT(data.m_headerWidgets.size() >= data.m_columnsCount);
        for (size_t i = 0; i < data.m_columnsCount; ++i)
        {
            // Extracting the widget from the frame
            auto frameChildren = Inspector::getChildren(data.m_headerWidgets[i]);
            auto zstackChildren = Inspector::getChildren(frameChildren[0]);
            if (zstackChildren.size() > 1)
            {
                // The first one is the background rectangle
                result.push_back(std::move(zstackChildren[1]));
            }
            else
            {
                result.push_back(nullptr);
            }
        }
    }
    else
    {
        for (size_t i = 0; i < data.m_columnsCount; ++i)
        {
            // Full with NULLs
            result.push_back(nullptr);
        }
    }

    // Nodes
    std::function<void(TreeView::Node*, bool)> fillRecursive;
    fillRecursive = [&result, &fillRecursive, this](TreeView::Node* node, bool isNodeVisible) {
        if (isNodeVisible)
        {
            for (const auto& widgets : node->widgetsForInspector)
            {
                // Extracting the branch from the ZStack
                auto branchChildren = Inspector::getChildren(widgets.first);
                if (branchChildren.size() > 1)
                {
                    // The first is the widget, the last is the button to collapse
                    result.push_back(std::move(branchChildren[0]));
                }
                else
                {
                    result.push_back(nullptr);
                }

                // Extracting the widget from the frame
                auto userWidgetChildren = Inspector::getChildren(widgets.second);
                if (!userWidgetChildren.empty())
                {
                    result.push_back(std::move(userWidgetChildren[0]));
                }
                else
                {
                    result.push_back(nullptr);
                }
            }
        }

        if (this->_isExpanded(node))
        {
            // Do the same for children if expanded.
            for (auto& child : node->children)
            {
                fillRecursive(child.get(), true);
            }
        }
    };

    fillRecursive(data.m_root.get(), this->isRootVisible());

    return result;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
