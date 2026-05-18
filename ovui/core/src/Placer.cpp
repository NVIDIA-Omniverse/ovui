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
#include "platform/Log.h"
#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/Frame.h>
#include <omni/ui/Placer.h>
#include <omni/ui/Workspace.h>

#include "ContainerData.h"

#include <algorithm>
#include <functional>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct Placer::PlacerData : public Container::ContainerData
{
    ~PlacerData() override = default;

    std::shared_ptr<Widget> m_childWidget;

    float m_offsetXCached;
    float m_offsetYCached;
    float m_widthCached;
    float m_heightCached;

    // Count duration when the mouse button is pressed. We need it to detect the second frame from mouse click.
    uint32_t m_pressedFrames = 0;

    // True when the user drags the child. We need it to know if the user was dragging the child on the previous frame.
    bool m_dragActive = false;
};

Placer::Placer()
    : Container(new PlacerData)
{
    this->_rasterHelperInit(*this);

    this->setSelectedChangedFn([this](const auto& selected) {
        this->_rasterHelperSetDirtyDrawList();

        auto& data = _getData<PlacerData>();
        if (data.m_childWidget)
        {
            data.m_childWidget->setSelected(selected);
        };
    });
    this->setCheckedChangedFn([this](const auto& checked) {
        this->_rasterHelperSetDirtyDrawList();

        auto& data = _getData<PlacerData>();
        if (data.m_childWidget)
        {
            data.m_childWidget->setChecked(checked);
        }
    });
    this->_setScaleChangedFn([this](const auto& scale) {
        this->_rasterHelperSetDirtyDrawList();

        auto& data = _getData<PlacerData>();
        if (data.m_childWidget)
        {
            data.m_childWidget->setScale(scale);
        }
    });
    this->_setCanvasZoomChangedFn([this](const auto& zoom) {
        auto& data = _getData<PlacerData>();
        if (data.m_childWidget)
        {
            data.m_childWidget->setCanvasZoom(zoom);
        }
    });
    this->setOffsetXChangedFn([this](Length const& offset) { this->forceWidthDirty(SizeDirtyReason::eSizeChanged); });
    this->setOffsetYChangedFn([this](Length const& offset) { this->forceHeightDirty(SizeDirtyReason::eSizeChanged); });
}

Placer::~Placer()
{
    OMNIUI_ASSERT(_getData<PlacerData>().m_drawCallData == nullptr);
    this->destroy();
}

void Placer::destroy()
{
    auto& data = _getData<PlacerData>();
    if (OMNIUI_UNLIKELY(data.destroy()))
    {
        return;
    }

    // TODO: Investigate whether this can go last, having it go first requires 
    // RasterHelper to check m_prv before any usage (105.1).
    //
    this->_rasterHelperDestroy();

    if (data.m_childWidget)
    {
        data.m_childWidget->destroy();
        data.m_childWidget->setParent(nullptr);
    }

    Widget::destroy();
}

void Placer::addChild(std::shared_ptr<Widget> widget)
{
    if (OMNIUI_UNLIKELY(!widget))
    {
        OMNIUI_LOG_ERROR("Placer::addChild attempting to add an invalid widget");
        return;
    }
    auto& data = _getData<PlacerData>();
    if (OMNIUI_UNLIKELY(data.addChild(widget)))
    {
        return;
    }

    this->_rasterHelperSetDirtyDrawList();

    data.m_childWidget = widget;
    widget->useMarginFromStyle(useMarginFromStyle());
    widget->setScale(this->_getScale());
    widget->setCanvasZoom(this->_getCanvasZoom());
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void Placer::clear()
{
    auto& data = _getData<PlacerData>();
    if (OMNIUI_UNLIKELY(data.clear()))
    {
        return;
    }

    data.m_childWidget = nullptr;
}

void Placer::setComputedContentWidth(float width)
{
    auto& data = _getData<PlacerData>();

    data.m_widthCached = width;
    const Length& offset = this->getOffsetX();
    if (offset.unit == UnitType::ePixel)
    {
        float uiScale = this->getDpiScale();
        data.m_offsetXCached = offset.value * uiScale;
    }
    else if (offset.unit == UnitType::ePercent)
    {
        data.m_offsetXCached = offset.value * width * 0.01f;
    }
    else // if (offset.unit == UnitType::eFraction)
    {
        data.m_offsetXCached = width;
    }

    if (data.m_childWidget && isWidthDirty() != SizeDirtyReason::eNone && data.m_childWidget->getWidth().unit != UnitType::ePixel)
    {
        data.m_childWidget->forceWidthDirty(SizeDirtyReason::eParentDirty);
    }

    if (this->isStableSize())
    {
        if (data.m_childWidget)
        {
            data.m_childWidget->setComputedWidth(width);
        }
        Widget::setComputedContentWidth(width);
        return;
    }

    // Child widget gwts the area available after offset:
    //
    //             Given length (width)
    // +---------------+-------------------------------+
    // |               |                               |
    // |   Offset X    |     Length left to Widget     |
    // +---------------+-----------------------------------------------+
    // |               |                                               |
    // |               | Child Widget has the same length as parent    |
    // |               |                                               |
    // +---------------+-----------------------------------------------+

    float computedWidth = data.m_offsetXCached;
    if (data.m_childWidget)
    {
        data.m_childWidget->setComputedWidth(Frame::_evaluateLayout(data.m_childWidget->getWidth(), width, this->getDpiScale()));
        computedWidth += data.m_childWidget->getComputedWidth();
    }

    Widget::setComputedContentWidth(std::max(width, computedWidth));
}

void Placer::setComputedContentHeight(float height)
{
    auto& data = _getData<PlacerData>();

    data.m_heightCached = height;
    const Length& offset = this->getOffsetY();
    if (offset.unit == UnitType::ePixel)
    {
        float uiScale = this->getDpiScale();
        data.m_offsetYCached = offset.value * uiScale;
    }
    else if (offset.unit == UnitType::ePercent)
    {
        data.m_offsetYCached = offset.value * height * 0.01f;
    }
    else // if (offset.unit == UnitType::eFraction)
    {
        data.m_offsetYCached = height;
    }

    if (data.m_childWidget && isHeightDirty() != SizeDirtyReason::eNone && data.m_childWidget->getHeight().unit != UnitType::ePixel)
    {
        data.m_childWidget->forceHeightDirty(SizeDirtyReason::eParentDirty);
    }

    if (this->isStableSize())
    {
        if (data.m_childWidget)
        {
            data.m_childWidget->setComputedHeight(height);
        }
        Widget::setComputedContentHeight(height);
        return;
    }

    // See Placer::setComputedContentWidth

    float computedHeight = data.m_offsetYCached;
    if (data.m_childWidget)
    {
        data.m_childWidget->setComputedHeight(Frame::_evaluateLayout(data.m_childWidget->getHeight(), height, this->getDpiScale()));
        computedHeight += data.m_childWidget->getComputedHeight();
    }

    Widget::setComputedContentHeight(std::max(height, computedHeight));
}

void Placer::cascadeStyle()
{
    Widget::cascadeStyle();

    this->_rasterHelperSetDirtyDrawList();

    auto& data = _getData<PlacerData>();
    if (data.m_childWidget)
    {
        data.m_childWidget->cascadeStyle();
    }
}

void Placer::forceRasterDirty(BakeDirtyReason reason)
{
    if (reason == BakeDirtyReason::eEditBegan)
    {
        this->_rasterHelperSuspendRasterization(true);
        this->_rasterHelperSetDirtyDrawList();
    }
    else if (reason == BakeDirtyReason::eEditEnded)
    {
        this->_rasterHelperSuspendRasterization(false);
        this->_rasterHelperSetDirtyDrawList();
    }
    else if (reason == BakeDirtyReason::eLodDirty)
    {
        auto& data = _getData<PlacerData>();
        if (OMNIUI_LIKELY(data.m_childWidget))
        {
            data.m_childWidget->forceRasterDirty(reason);
        }

        this->_rasterHelperSetDirtyLod();
    }
    else
    {
        this->_rasterHelperSetDirtyDrawList();
    }

    Widget::forceRasterDirty(reason);
}

void Placer::_drawContent(float elapsedTime)
{
    auto& data = _getData<PlacerData>();

    // The isVisible check is important for OM-55727
    if (!data.m_childWidget || !data.m_childWidget->isVisible())
    {
        return;
    }

    Container::ContainerData::DrawCallData drawCache(std::static_pointer_cast<Container>(shared_from_this()), data);

    ImVec2 childContentSize{ data.m_childWidget->getComputedWidth(), data.m_childWidget->getComputedHeight() };
    // XXX: Previous code early exited here based on if (childContentSize.x <= 0.0f || childContentSize.y <= 0.0f)
    // stating ImGui doesn't like 0 size.  But this caused issues with this (OM-70187):
    // ui.Placer
    //   ui.ZStack()
    //     ui.Rectangle()
    //     ui.Label()
    // Where label transitions from empty to non-empty string.
    //
    // ImGui::BeginChild currently checks for <= 0 size and expands to 4.


    auto previousCursor = ImGui::GetCursorScreenPos();
    auto currentCursor = previousCursor;

    float uiScale = this->getDpiScale();
    currentCursor.x += data.m_offsetXCached;
    currentCursor.y += data.m_offsetYCached;

    ImGui::SetCursorScreenPos(currentCursor);

    // isDraggable can be changed when the child widget is called.
    bool draggable = this->isDraggable();
    bool doRaster = this->getRasterPolicy() != RasterPolicy::eNever;
    bool iterateChildren = true;
    if (draggable)
    {
        // We need to create a non-movable child window to detect the hovering when multiple placers put their widgets
        // to the same place. The alternative is using ImGui::IsItemHovered but it picks the item that is on the bottom.
        // We need to pick the item on the top. So far ImGui::IsWindowHovered is the only way to do it.
        // TODO: Draw window only if this region is under the mouse pointer. Should be easy to do.
        ImGui::PushStyleVar(ImGuiStyleVar_ChildRounding, 0.0f);
        ImGui::PushStyleVar(ImGuiStyleVar_ChildBorderSize, 0.0f);
        ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2{ 0.0f, 0.0f });

        if (doRaster)
        {
            iterateChildren =
                this->_rasterHelperBegin(currentCursor.x, currentCursor.y, childContentSize.x, childContentSize.y);
        }
        else
        {
            ImGui::BeginChild(ImGui::GetID(this), childContentSize,
                              ImGuiChildFlags_AlwaysUseWindowPadding,
                              ImGuiWindowFlags_NoMove |
                                  ImGuiWindowFlags_NoBackground | ImGuiWindowFlags_NoScrollbar |
                                  ImGuiWindowFlags_NoScrollWithMouse);
        }

        ImGui::PopStyleVar(3);
    }

    if (iterateChildren)
    {
        // here we will move the cursor by the offset and the Anchor
        data.m_childWidget->draw(elapsedTime);
    }

    if (draggable)
    {
        // Check if it's the top child window. It's false if there is another window on the top of this one.
        auto ctx = ImGui::GetCurrentContext();
        bool forceStartDrag = data.m_pressedFrames < this->getFramesToStartDrag() && ctx->HoveredWindow == ctx->CurrentWindow;
        bool hovered = ImGui::IsWindowHovered(ImGuiHoveredFlags_None);
        // Using m_dragActive to determine if the user already drags it. For example when the user took the node and
        // drags it to another node. The another node should not become draggable.
        data.m_dragActive = (data.m_dragActive || hovered || forceStartDrag) && isPressed(0);

        if (isPressed(0))
        {
            data.m_pressedFrames++;
        }
        else if (data.m_pressedFrames > 0)
        {
            data.m_pressedFrames = 0;
        }

        if (doRaster)
        {
            this->_rasterHelperEnd();
        }
        else
        {
            ImGui::EndChild();
        }

        // Show the resize cursor when hovered without requiring dragging being active,
        // to be consistent with other widgets
        if (hovered || data.m_dragActive)
        {
            Axis axis = this->getDragAxis();
            if (axis == Axis::eX)
            {
                ImGui::SetMouseCursor(ImGuiMouseCursor_ResizeEW);
            }
            else if (axis == Axis::eY)
            {
                ImGui::SetMouseCursor(ImGuiMouseCursor_ResizeNS);
            }
        }

        if (data.m_dragActive)
        {
            const ImGuiIO& io = ImGui::GetIO();
            const auto& mouseDelta = io.MouseDelta;

            // Move it in the next frame.
            Axis axis = this->getDragAxis();
            if (axis == Axis::eX || axis == Axis::eXY)
            {
                Length offset = this->getOffsetX();
                if (offset.unit == UnitType::ePixel)
                {
                    offset.value += mouseDelta.x / uiScale;
                }
                else if (offset.unit == UnitType::ePercent)
                {
                    offset.value += mouseDelta.x / data.m_widthCached * 100.f;
                }

                this->setOffsetX(offset);
            }

            if (axis == Axis::eY || axis == Axis::eXY)
            {
                Length offset = this->getOffsetY();
                if (offset.unit == UnitType::ePixel)
                {
                    offset.value += mouseDelta.y / uiScale;
                }
                else if (offset.unit == UnitType::ePercent)
                {
                    offset.value += mouseDelta.y / data.m_heightCached * 100.f;
                }

                this->setOffsetY(offset);
            }
        }
    }

    ImGui::SetCursorScreenPos(previousCursor);
}

std::vector<std::shared_ptr<Widget>> Placer::_getChildren() const
{
    std::vector<std::shared_ptr<Widget>> rval;

    auto& data = _getData<PlacerData>();
    if (data.m_childWidget)
    {
        rval.emplace_back(data.m_childWidget);
    }
    return rval;
}

void Placer::_fillVisibleThreshold(void* thresholds) const
{
    Widget::_fillVisibleThreshold(thresholds);

    auto& data = _getData<PlacerData>();
    if (OMNIUI_LIKELY(data.m_childWidget))
    {
        data.m_childWidget->_fillVisibleThreshold(thresholds);
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
