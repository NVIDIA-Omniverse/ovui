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
#include <omni/ui/Profile.h>
#include <omni/ui/StyleProperties.h>

#include "FrameData.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

void _moveDrawList(ImDrawList* drawList, ImVec2 delta)
{
    if (delta.x == 0.0f && delta.y == 0.0f)
    {
        return;
    }

    for (auto& vertex : drawList->VtxBuffer)
    {
        vertex.pos.x += delta.x;
        vertex.pos.y += delta.y;
    }

    for (auto& command : drawList->CmdBuffer)
    {
        command.ClipRect.x += delta.x;
        command.ClipRect.y += delta.y;
        command.ClipRect.z += delta.x;
        command.ClipRect.w += delta.y;
    }
}

Frame::FrameData::~FrameData()
{
}

Frame::Frame(FrameData* data) : Frame(true, data)
{
}

Frame::Frame(bool needsPadding, FrameData* dataPtr)
    : Container(dataPtr ? dataPtr : new FrameData)
{
    _getData<FrameData>().m_needPadding = needsPadding;

    this->_rasterHelperInit(*this);

    this->setSelectedChangedFn([this](const auto& selected) {
        this->_rasterHelperSetDirtyDrawList();

        auto& data = _getData<FrameData>();
        if (data.m_canvas)
        {
            data.m_canvas->setSelected(selected);
        }
        if (data.m_canvasPending)
        {
            data.m_canvasPending->setSelected(selected);
        }
    });
    this->setCheckedChangedFn([this](const auto& checked) {
        this->_rasterHelperSetDirtyDrawList();

        auto& data = _getData<FrameData>();
        if (data.m_canvas)
        {
            data.m_canvas->setChecked(checked);
        }
        if (data.m_canvasPending)
        {
            data.m_canvasPending->setChecked(checked);
        }
    });
    this->setEnabledChangedFn([this](const auto& enabled) {
        this->_rasterHelperSetDirtyDrawList();

        auto& data = _getData<FrameData>();
        if (data.m_canvas)
        {
            data.m_canvas->setEnabled(enabled);
        }
        if (data.m_canvasPending)
        {
            data.m_canvasPending->setEnabled(enabled);
        }
    });
    this->_setScaleChangedFn([this](const auto& scale) {
        this->_rasterHelperSetDirtyDrawList();

        auto& data = _getData<FrameData>();
        if (data.m_canvas)
        {
            data.m_canvas->setScale(scale);
        }
        if (data.m_canvasPending)
        {
            data.m_canvasPending->setScale(scale);
        }
    });
    this->_setCanvasZoomChangedFn([this](const auto& zoom) {
        auto& data = _getData<FrameData>();
        if (data.m_canvas)
        {
            data.m_canvas->setCanvasZoom(zoom);
        }
        if (data.m_canvasPending)
        {
            data.m_canvasPending->setCanvasZoom(zoom);
        }
    });
    this->setBuildChangedFn([this]() {
        this->_rasterHelperSetDirtyDrawList();
        this->rebuild();
    });
    this->_setRasterPolicyChangedFn([this](const auto& policy) {
        if (policy != RasterPolicy::eNever)
        {
            this->_rasterHelperSetDirtyDrawList();
        }
    });
    this->_setFrozenChangedFn([this](const auto& frozen) {
        if (!frozen)
        {
            auto& data = _getData<FrameData>();
            data.m_drawList.reset(nullptr);
        }
    });
}

Frame::~Frame()
{
    OMNIUI_ASSERT(_getData<FrameData>().m_drawCallData == nullptr);
    this->destroy();
}

void Frame::destroy()
{
    auto& data = _getData<FrameData>();
    if (OMNIUI_UNLIKELY(data.destroy()))
    {
        return;
    }

    this->clear();

    Container::destroy();

    this->_rasterHelperDestroy();
}

void Frame::addChild(std::shared_ptr<Widget> canvas)
{
    if (OMNIUI_UNLIKELY(!canvas))
    {
        OMNIUI_LOG_ERROR("Stack::addChild attempting to add an invalid widget");
        return;
    }

    auto& data = _getData<FrameData>();
    if (data.addChild(canvas))
    {
        return;
    }

    this->_rasterHelperSetDirtyDrawList();

    // TODO: m_canvas and m_canvasPending should be re-thought in terms of the pattern from _drawContent
    // in relation to Frame::clear and Frame::destroy..

    // When addChild is called, the current Frame widget should be replaced by the given one. The problem is it can be
    // called during the draw cycle from the child of Frame. In this case, the child that called it will be destroyed,
    // and as a result, it will crash. To avoid it, we save the given widget and will replace it outside of the draw
    // cycle.
    //
    // NOTE: If m_canvasPending exists and is valid, then addChild(...) has been called multiple times before
    // _processPendingWidget was ever invoked.  In those cases, detach current m_canvasPending (which should never
    // have made it into a draw cycle?) before replacing it.
    //
    // This codepath can currently be triggered with:
    //  tests-omni.kit.test_suite.browser.bat -f test_content_browser_settings
    //
    if (data.m_canvasPending)
    {
        data.m_canvasPending->setParent(nullptr);
        data.m_canvasPending.reset();
    }
    data.m_canvasPending = std::move(canvas);
    data.m_canvasPending->useMarginFromStyle(useMarginFromStyle());

    data.m_canvasPending->setSelected(this->isSelected());
    data.m_canvasPending->setChecked(this->isChecked());
    data.m_canvasPending->setEnabled(this->isEnabled());
    data.m_canvasPending->setScale(this->_getScale());
    data.m_canvasPending->setCanvasZoom(this->_getCanvasZoom());

    this->forceWidthDirty(SizeDirtyReason::eChildDirty);
    this->forceHeightDirty(SizeDirtyReason::eChildDirty);
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void Frame::clear()
{
    auto& data = _getData<FrameData>();
    if (OMNIUI_UNLIKELY(data.clear()))
    {
        return;
    }

    if (std::shared_ptr<Widget> canvas = std::exchange(data.m_canvas, std::shared_ptr<Widget>()))
    {
        canvas->destroy();
        canvas->setParent(nullptr);
    }
    if (std::shared_ptr<Widget> canvasPending = std::exchange(data.m_canvasPending, std::shared_ptr<Widget>()))
    {
        canvasPending->destroy();
        canvasPending->setParent(nullptr);
    }

    this->forceWidthDirty(SizeDirtyReason::eChildDirty);
    this->forceHeightDirty(SizeDirtyReason::eChildDirty);
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void Frame::setComputedContentWidth(float width)
{
    this->_processPendingWidget();

    auto& data = _getData<FrameData>();

    // Get padding.
    float padding = 0.0f;
    if (data.m_needPadding && this->_resolveStyleProperty(StyleFloatProperty::ePadding, &padding) && padding != 0.0f)
    {
        float dpiScale = this->getDpiScale();
        padding *= dpiScale;
    }

    float widthMinusPadding = std::max(width - padding * 2.0f, 0.0f);

    auto& canvas = data.m_canvas;
    if (canvas && canvas->isVisible())
    {
        if (isWidthDirty() != SizeDirtyReason::eNone && canvas->getWidth().unit != UnitType::ePixel)
        {
            canvas->forceWidthDirty(SizeDirtyReason::eParentDirty);
        }

        float childLayoutWidth = This::_evaluateLayout(canvas->getWidth(), widthMinusPadding, this->getDpiScale());
        canvas->setComputedWidth(childLayoutWidth);

        if (!this->isHorizontalClipping())
        {
            widthMinusPadding = canvas->getComputedWidth();
        }
    }

    Widget::setComputedContentWidth(widthMinusPadding + padding * 2.0f);
}

void Frame::setComputedContentHeight(float height)
{
    this->_processPendingWidget();

    auto& data = _getData<FrameData>();

    // Get padding.
    float padding = 0.0f;
    if (data.m_needPadding && this->_resolveStyleProperty(StyleFloatProperty::ePadding, &padding))
    {
        float dpiScale = this->getDpiScale();
        padding *= dpiScale;
    }

    float heightMinusPadding = std::max(height - padding * 2.0f, 0.0f);

    auto& canvas = data.m_canvas;
    if (canvas && canvas->isVisible())
    {
        if (isHeightDirty() != SizeDirtyReason::eNone && canvas->getHeight().unit != UnitType::ePixel)
        {
            canvas->forceHeightDirty(SizeDirtyReason::eParentDirty);
        }

        float childLayoutHeight = This::_evaluateLayout(canvas->getHeight(), heightMinusPadding, this->getDpiScale());
        canvas->setComputedHeight(childLayoutHeight);

        if (!this->isVerticalClipping())
        {
            heightMinusPadding = canvas->getComputedHeight();
        }
    }

    Widget::setComputedContentHeight(heightMinusPadding + padding * 2.0f);
}

void Frame::cascadeStyle()
{
    Widget::cascadeStyle();

    this->_rasterHelperSetDirtyDrawList();

    // Propagate style change to the children.

    auto& data = _getData<FrameData>();
    if (data.m_canvas)
    {
        data.m_canvas->cascadeStyle();
    }
    if (data.m_canvasPending)
    {
        data.m_canvasPending->cascadeStyle();
    }
}

void Frame::forceRasterDirty(BakeDirtyReason reason)
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
        auto& data = _getData<FrameData>();
        if (OMNIUI_LIKELY(data.m_canvas))
        {
            data.m_canvas->forceRasterDirty(reason);
        }
        if (OMNIUI_UNLIKELY(data.m_canvasPending))
        {
            data.m_canvasPending->forceRasterDirty(reason);
        }

        this->_rasterHelperSetDirtyLod();
    }
    else
    {
        this->_rasterHelperSetDirtyDrawList();
    }

    Widget::forceRasterDirty(reason);
}

void Frame::rebuild()
{
    auto& data = _getData<FrameData>();
    data.m_drawList.reset(nullptr);
    this->_rasterHelperSetDirtyDrawList();
    data.m_needRebuildWithCallback = true;
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void Frame::setVisiblePreviousFrame(bool wasVisible, bool dirtySize)
{
    if (!wasVisible)
    {
        auto& data = _getData<FrameData>();
        if (data.m_canvas)
        {
            data.m_canvas->setVisiblePreviousFrame(wasVisible, false);
        }
        if (data.m_canvasPending)
        {
            data.m_canvasPending->setVisiblePreviousFrame(wasVisible, false);
        }
    }

    Widget::setVisiblePreviousFrame(wasVisible, dirtySize);
}

void Frame::_drawContent(float elapsedTime)
{
    // This is delayed until after this->_populate as it is known to call the build-fn and allow
    // children being added.  We still want to error on calling clear or destroy for now.
    //
    auto& data = _getData<FrameData>();

    Container::ContainerData::DrawCallData drawCache(std::static_pointer_cast<Container>(shared_from_this()), data, true);

    if (data.m_needRebuildWithCallback && this->hasBuildFn())
    {
        auto* ctx = ImGui::GetCurrentContext();
        ImGuiWindow* window = ctx->CurrentWindow;

        // Hidden means either the window is closed or another window is active on the same dock tab.
        // Appearing means it's just created and is not yet displayed. We need to check the Appearing flag because on
        // the first frame the window is created it's always not hidden.
        if (this->_isInRasterWindow() || (!window->Hidden && !window->Appearing))
        {
            ImVec2 computedContentSize{ this->getComputedContentWidth(), this->getComputedContentHeight() };
            if (ImGui::IsRectVisible(computedContentSize))
            {
                this->_populate();
            }
        }
    }

    // Calling Frame::addChild will error after this
    //
    drawCache.disAllowAddChildren();


    if (!data.m_canvas)
    {
        // If it's the first drawing cycle this Frame is drawn, and we specified build_fn, we have a pending widget. We
        // need to use it, otherwise this Frame will be empty the first frame.
        this->_processPendingWidget();

        if (data.m_canvas)
        {
            this->setComputedContentWidth(this->getComputedContentWidth());
            this->setComputedContentHeight(this->getComputedContentHeight());
        }
        else
        {
            return;
        }
    }

    // Set padding.
    float padding = 0.0f;
    if (data.m_needPadding && this->_resolveStyleProperty(StyleFloatProperty::ePadding, &padding))
    {
        float dpiScale = this->getDpiScale();
        padding *= dpiScale;

        if (padding != 0.0f)
        {
            auto cursor = ImGui::GetCursorScreenPos();
            cursor.x += padding;
            cursor.y += padding;

            ImGui::SetCursorScreenPos(cursor);
        }
    }

    // Set dirty if the size is changed
    float width = this->getComputedContentWidth();
    float height = this->getComputedContentHeight();
    auto cursor = ImGui::GetCursorScreenPos();

    // Raster logic
    bool doRaster = this->getRasterPolicy() != RasterPolicy::eNever;
    bool iterateChildren;
    bool needSeparateWindow;

    if (doRaster)
    {
        ImVec2 rasterOrigin = cursor;
        auto* ctx = ImGui::GetCurrentContext();
        ImGuiWindow* window = ctx ? ctx->CurrentWindow : nullptr;
        if (window)
        {
            rasterOrigin.x = std::max(rasterOrigin.x, window->ClipRect.Min.x);
            rasterOrigin.y = std::max(rasterOrigin.y, window->ClipRect.Min.y);
        }

        iterateChildren = this->_rasterHelperBegin(rasterOrigin.x, rasterOrigin.y, width, height);
        needSeparateWindow = false;
    }
    else
    {
        // Window flags
        iterateChildren = true;
        needSeparateWindow = this->isSeparateWindow();
    }

    bool frozen = this->isFrozen();
    if (needSeparateWindow || frozen)
    {
        // Extend the child window to the full available area, so children are not clipped
        auto* ctx = ImGui::GetCurrentContext();
        ImGuiWindow* window = ctx->CurrentWindow;
        const ImRect& clipRect = window->ClipRect;

        auto childWindowPos = clipRect.Min;
        auto childWindowSize = ImVec2{ clipRect.Max.x - clipRect.Min.x, clipRect.Max.y - clipRect.Min.y };
        auto windowFlags = ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse |
                           ImGuiWindowFlags_NoMouseInputs | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoMove;

        // Extend the child window to the full available area, so children are not clipped
        ImGui::SetCursorScreenPos(childWindowPos);

        // WindowFlagNoBackground doesn't work
        ImGui::SetNextWindowBgAlpha(0.0f);

        ImGui::PushID(this);

        if ((window->Flags & ImGuiWindowFlags_Tooltip) == ImGuiWindowFlags_Tooltip)
        {
            // This is a hack to prevent windows from being created inside tooltips.
            // This was not intended behavior, but we have received complaints
            // about windows behaving oddly when created inside tooltips.
            // In this solution, we do not provide the window size if it is
            // created inside a tooltip.
            childWindowSize = ImVec2{ 0.0f, 0.0f };
        }

        ImGui::BeginChild("", childWindowSize, false, windowFlags);

        // Restore the cursor
        ImGui::SetCursorScreenPos(cursor);
    }

    bool clipping = this->isHorizontalClipping() || this->isVerticalClipping();

    if (clipping)
    {
        auto cursor = ImGui::GetCursorScreenPos();
        ImVec2 rectMax{ this->getComputedContentWidth() - padding * 2.0f,
                        this->getComputedContentHeight() - padding * 2.0f };
        ImGui::GetWindowDrawList()->PushClipRect(
            ImFloor(cursor), ImFloor(ImVec2{ cursor.x + rectMax.x, cursor.y + rectMax.y }), true);
    }

    if (data.m_drawList && frozen)
    {
        _moveDrawList(data.m_drawList.get(),
                      { cursor.x - data.m_drawListPosition.x, cursor.y - data.m_drawListPosition.y });
        data.m_drawListPosition = cursor;

        ImDrawList* drawList = ImGui::GetWindowDrawList();
        drawList->CmdBuffer = data.m_drawList->CmdBuffer;
        drawList->IdxBuffer = data.m_drawList->IdxBuffer;
        drawList->VtxBuffer = data.m_drawList->VtxBuffer;
        drawList->Flags = data.m_drawList->Flags;
    }
    else if (iterateChildren)
    {
        data.m_canvas->draw(elapsedTime);
    }

    if (clipping)
    {
        ImGui::GetWindowDrawList()->PopClipRect();
    }

    if (doRaster)
    {
        this->_rasterHelperEnd();
    }
    if (needSeparateWindow || frozen)
    {
        if (!data.m_drawList && frozen)
        {
            // Save draw list
            data.m_drawList.reset(ImGui::GetWindowDrawList()->CloneOutput());
            data.m_drawListPosition = cursor;
        }
        ImGui::EndChild();
        ImGui::PopID();
    }

    if (data.m_canvasPending)
    {
        // It will call `this->_processPendingWidget();`. We can't call it in
        // draw because m_canvas will be removed. We can't remove widgets in the
        // middle of draw.
        this->forceWidthDirty(SizeDirtyReason::eChildDirty);
        this->forceHeightDirty(SizeDirtyReason::eChildDirty);
    }
}

std::vector<std::shared_ptr<Widget>> Frame::_getChildren() const
{
    auto& data = _getData<FrameData>();

    if (data.m_canvasPending)
    {
        return { data.m_canvasPending };
    }

    if (data.m_canvas)
    {
        return { data.m_canvas };
    }

    return {};
}

void Frame::_fillVisibleThreshold(void* thresholds) const
{
    Widget::_fillVisibleThreshold(thresholds);

    auto& data = _getData<FrameData>();
    if (OMNIUI_LIKELY(data.m_canvas))
    {
        data.m_canvas->_fillVisibleThreshold(thresholds);
    }
}

float Frame::_evaluateLayout(const Length& canvasLength, float availableLength, float dpiScale)
{
    float computedLength;
    if (canvasLength.unit == UnitType::ePixel)
    {
        computedLength = canvasLength.value * dpiScale;
    }
    else if (canvasLength.unit == UnitType::ePercent)
    {
        computedLength = canvasLength.value * 1e-2f * availableLength;
    }
    else // if (currentWidth.unit == UnitType::eFraction)
    {
        computedLength = availableLength;
    }

    return computedLength;
}

void Frame::_processPendingWidget()
{
    auto& data = _getData<FrameData>();
    if (data.m_canvasPending)
    {
        if (data.m_canvas)
        {
            data.m_canvas->setParent(nullptr);
        }

        data.m_canvas.swap(data.m_canvasPending);
        data.m_canvasPending.reset();
    }
}

void Frame::_populate()
{
    OMNIUI_PROFILE_VERBOSE_WIDGET_FUNCTION;

    auto& data = _getData<FrameData>();
    if (data.m_needRebuildWithCallback && this->hasBuildFn())
    {
        // Call the build function and put the created widgets to this frame.
        OMNIKIT_WITH_CONTAINER(this->castShared())
        {
            this->callBuildFn();
        }

        data.m_needRebuildWithCallback = false;
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
