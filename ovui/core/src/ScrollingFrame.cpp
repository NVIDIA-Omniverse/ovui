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

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/ScrollingFrame.h>
#include <omni/ui/StyleContainer.h>

#include "FrameData.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

// Override ScrollbarSize of ImGui even if we don't have it in style because the one from ImGui is not properly DPI
// scalable. All ovui widgets should be properly DPI scaled.
constexpr float kScrollBarWidth = 12.0f;

struct ScrollingFrame::ScrollingFrameData : public Frame::FrameData
{
    static ScrollingFrameData& getData(const ScrollingFrame* frame)
    {
        return static_cast<ScrollingFrameData&>(*frame->m_data);
    }

    ~ScrollingFrameData() override = default;

    // Flags for synchronization of the scrollX and scrollY properties and the underlying windowing system.
    bool m_scrollXExplicitlyChanged = false;
    bool m_scrollYExplicitlyChanged = false;
};


ScrollingFrame::ScrollingFrame() : Frame(new ScrollingFrameData)
{
    this->setScrollXChangedFn(std::bind(&ScrollingFrame::_scrollXExplicitlyChanged, this));
    this->setScrollYChangedFn(std::bind(&ScrollingFrame::_scrollYExplicitlyChanged, this));
}

ScrollingFrame::~ScrollingFrame() = default;

void ScrollingFrame::setComputedContentWidth(float width)
{
    float dpiScale = this->getDpiScale();
    float scrollbarWidth = kScrollBarWidth * dpiScale;

    if (this->getVerticalScrollBarPolicy() == ScrollBarPolicy::eScrollBarAlwaysOn)
    {
        if (this->_resolveStyleProperty(StyleFloatProperty::eScrollbarSize, &scrollbarWidth))
        {
            scrollbarWidth *= dpiScale;
        }
    }
    else if (this->getVerticalScrollBarPolicy() == ScrollBarPolicy::eScrollBarAlwaysOff)
    {
        scrollbarWidth = 0.0f;
    }
    // TODO: eScrollBarAsNeeded

    // The canvas should be less if there is a scrollbar. We use the base class to set the size of children.
    Frame::setComputedContentWidth(width - scrollbarWidth);

    Widget::setComputedContentWidth(width);
}

void ScrollingFrame::setComputedContentHeight(float height)
{
    float dpiScale = this->getDpiScale();
    float scrollbarWidth = kScrollBarWidth * dpiScale;

    if (this->getHorizontalScrollBarPolicy() == ScrollBarPolicy::eScrollBarAlwaysOn)
    {
        if (this->_resolveStyleProperty(StyleFloatProperty::eScrollbarSize, &scrollbarWidth))
        {
            scrollbarWidth *= dpiScale;
        }
    }
    else if (this->getHorizontalScrollBarPolicy() == ScrollBarPolicy::eScrollBarAlwaysOff)
    {
        scrollbarWidth = 0.0f;
    }
    // TODO: eScrollBarAsNeeded

    // The canvas should be less if there is a scrollbar. We use the base class to set the size of children.
    Frame::setComputedContentHeight(height - scrollbarWidth);

    Widget::setComputedContentHeight(height);
}

void ScrollingFrame::_drawContent(float elapsedTime)
{
    if (this->getComputedContentWidth() <= 0.0f || this->getComputedContentHeight() <= 0.0f)
    {
        // ImGui is not good with zeros
        return;
    }

    uint32_t color;
    int pushedColorCounter = 0;
    int pushedVarCounter = 0;

    ImGui::PushStyleColor(ImGuiCol_ScrollbarBg, 0x0);
    pushedColorCounter++;

    if (this->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &color))
    {
        // Push and Pop are very cheap in ImGui because ImVector never decreases capacity.
        ImGui::PushStyleColor(ImGuiCol_ChildBg, color);
        pushedColorCounter++;
    }

    if (this->_resolveStyleProperty(StyleColorProperty::eSecondaryColor, &color))
    {
        // Push and Pop are very cheap in ImGui because ImVector never decreases capacity.
        ImGui::PushStyleColor(ImGuiCol_ScrollbarGrab, color);
        ImGui::PushStyleColor(ImGuiCol_ScrollbarGrabHovered, color);
        ImGui::PushStyleColor(ImGuiCol_ScrollbarGrabActive, color);
        pushedColorCounter += 3;
    }

    float scrollbarSize = kScrollBarWidth;
    this->_resolveStyleProperty(StyleFloatProperty::eScrollbarSize, &scrollbarSize);
    // Override ScrollbarSize of ImGui even if we don't have it in style because the one from ImGui is not properly DPI
    // scalable.
    float dpiScale = this->getDpiScale();
    ImGui::PushStyleVar(ImGuiStyleVar_ScrollbarSize, scrollbarSize * dpiScale);
    // 2.0 is the gap between inner and outer rectangle of scrolling frame that is hardcoded in ImGui::ScrollbarEx.
    // See the lines:
    //   ImRect bb = bb_frame;
    //   bb.Expand(...)
    float scrollbarRounding = 0.5f * scrollbarSize * dpiScale - 2.0f;
    this->_resolveStyleProperty(StyleFloatProperty::eBorderRadius, &scrollbarRounding);
    ImGui::PushStyleVar(ImGuiStyleVar_ScrollbarRounding, scrollbarRounding * dpiScale);
    pushedVarCounter += 2;

    const auto& name = this->getName();

    // We need to use the name is ImGui ID because otherwise, when creating the ImGui child with a specific scroll
    // position, at the first frame, it will be at position 0, and the second frame, it will be at the specified
    // position. Such behavior of ImGui makes the UI blinking. With the name in the ID, it doesn't happen.
    if (!name.empty())
    {
        ImGui::PushID(name.c_str());
    }
    else
    {
        ImGui::PushID(this);
    }

    auto horizontalPolicy = this->getHorizontalScrollBarPolicy();
    auto verticalPolicy = this->getVerticalScrollBarPolicy();

    auto* ctx = ImGui::GetCurrentContext();
    ImGuiWindow* window = ctx->CurrentWindow;

    // ImGui has very limited control on scrollbars. This is everything it has:
    // ImGuiWindowFlags_NoScrollbar            = 1 << 3,   // Disable scrollbars (window can still scroll with mouse or
    //                                                     // programmatically)
    // ImGuiWindowFlags_HorizontalScrollbar    = 1 << 11,  // Allow horizontal scrollbar to appear (off by default). You
    //                                                     // may use SetNextWindowContentSize(ImVec2(width,0.0f));
    //                                                     // prior to calling Begin() to specify width. Read code in
    //                                                     // imgui_demo in the "Horizontal Scrolling" section.
    // ImGuiWindowFlags_AlwaysVerticalScrollbar= 1 << 14,  // Always show vertical scrollbar
    // ImGuiWindowFlags_AlwaysHorizontalScrollbar=1<< 15,  // Always show horizontal scrollbar
    //
    // And it means that some of the h/v scrollbar combination modes will not be supported.
    // TODO: If we add own scrollbar, we can tonrol it with a better way.
    ImGuiWindowFlags flags = window->Flags & ImGuiWindowFlags_NoMouseInputs;
    if (horizontalPolicy == ScrollBarPolicy::eScrollBarAlwaysOff && verticalPolicy == ScrollBarPolicy::eScrollBarAlwaysOff)
    {
        flags |= ImGuiWindowFlags_NoScrollbar;
    }
    else
    {
        if (horizontalPolicy == ScrollBarPolicy::eScrollBarAlwaysOn)
        {
            flags |= ImGuiWindowFlags_AlwaysHorizontalScrollbar;
        }
        else if (horizontalPolicy == ScrollBarPolicy::eScrollBarAsNeeded)
        {
            flags |= ImGuiWindowFlags_HorizontalScrollbar;
        }
        else // if (horizontalPolicy == ScrollBarPolicy::eScrollBarAlwaysOff)
        {
            // It's by default in ImGui
        }

        if (verticalPolicy == ScrollBarPolicy::eScrollBarAlwaysOn)
        {
            flags |= ImGuiWindowFlags_AlwaysVerticalScrollbar;
        }
        else if (verticalPolicy == ScrollBarPolicy::eScrollBarAsNeeded)
        {
            // It's by default in ImGui
        }
        else // if (verticalPolicy == ScrollBarPolicy::eScrollBarAlwaysOff)
        {
            // Not supported.
        }
    }

    // Create a window with the specified size.
    ImGui::BeginChild("", { this->getComputedContentWidth(), this->getComputedContentHeight() }, false, flags);

    // Two-way synchronization of ImGui scroll and the scroll property. The problem here is ImGui::SetScroll sets
    // ImGuiWindow.ScrollTarget and ImGui::GetScroll returns ImGuiWindow.Scroll. And it assigns ScrollTarget to Scroll
    // in the function BeginChild. It means if we set property and ImGui scroll at the same time without flags, it will
    // be working like a pendulum in the first frame the scroll will be displayed correctly, but in the second frame, it
    // will return to the initial value. To avoid it, we use the flag that indicates that the scroll level was changed.
    // It allows us to obtain the correct scroll from ImGui and send it back to ImGui if it was changed, so it's very
    // transparent to the user.
    auto& data = _getData<ScrollingFrameData>();
    if (data.m_scrollXExplicitlyChanged)
    {
        ImGui::SetScrollX(this->getScrollX() * dpiScale);
        data.m_scrollXExplicitlyChanged = false;
    }
    else
    {
        this->setScrollX(ImGui::GetScrollX() / dpiScale);
        this->setScrollXMax(ImGui::GetScrollMaxX() / dpiScale);
    }

    if (data.m_scrollYExplicitlyChanged)
    {
        ImGui::SetScrollY(this->getScrollY() * dpiScale);
        data.m_scrollYExplicitlyChanged = false;
    }
    else
    {
        this->setScrollY(ImGui::GetScrollY() / dpiScale);
        this->setScrollYMax(ImGui::GetScrollMaxY() / dpiScale);
    }

    // Base _drawContent works nice. We only need to frame it to the scrolling window.
    Frame::_drawContent(elapsedTime);

    ImGui::EndChild();
    ImGui::PopID();

    ImGui::PopStyleVar(pushedVarCounter);
    ImGui::PopStyleColor(pushedColorCounter);
}

void ScrollingFrame::_scrollXExplicitlyChanged()
{
    _getData<ScrollingFrameData>().m_scrollXExplicitlyChanged = true;
}

void ScrollingFrame::_scrollYExplicitlyChanged()
{
    _getData<ScrollingFrameData>().m_scrollYExplicitlyChanged = true;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
