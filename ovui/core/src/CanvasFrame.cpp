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
#include <omni/ui/CanvasFrame.h>
#include "platform/CanvasFrameGuard.h"
#include <omni/ui/Label.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/Workspace.h>

#include "FrameData.h"

#include <math.h>
#include <unordered_set>
#include <algorithm>

OMNIUI_NAMESPACE_OPEN_SCOPE

// When setting the clipping range to [-FLOAT_MAX..FLOAT_MAX] to ensure that
// connections are not clipped, ImGui converts it to [FLOAT_MIN..FLOAT_MIN],
// which causes the connections between nodes to be clipped and not displayed. I
// noticed this issue after using the IM_FLOOR macro, which converts float
// values to integers by casting them to int. This means that although it is a
// float variable, it should be set to the int maximum limit. However, ImGui
// also calculates width and height, which should also be less than the int
// limit. That's why using INT32_MAX / 2 does not work, because the width and
// height calculated using this limit are more than the limit by 1. That's why
// the constant INT32_MAX \ 4 is used instead.
constexpr float kFloatMax = (float)(INT32_MAX / 4);

struct CanvasFrame::CanvasFrameData : public Frame::FrameData
{
    // ImGui state
    float m_ctxIOMousePosX = 0.0f;
    float m_ctxIOMousePosY = 0.0f;
    float m_ctxIOMouseDeltaX = 0.0f;
    float m_ctxIOMouseDeltaY = 0.0f;
    float m_ctxMouseViewportPosX = 0.0f;
    float m_ctxMouseViewportPosY = 0.0f;
    float m_ctxMouseViewportSizeX = 0.0f;
    float m_ctxMouseViewportSizeY = 0.0f;
    float m_ctxCurrentWindowPosX = 0.0f;
    float m_ctxCurrentWindowPosY = 0.0f;
    float m_ctxCurrentWindowSizeX = 0.0f;
    float m_ctxCurrentWindowSizeY = 0.0f;
    float m_ctxCurrentWindowClipRectMinX = 0.0f;
    float m_ctxCurrentWindowClipRectMinY = 0.0f;
    float m_ctxCurrentWindowClipRectMaxX = 0.0f;
    float m_ctxCurrentWindowClipRectMaxY = 0.0f;
    ImVector<ImVec4> m_clipRectStack;
    // ImGui 1.92.7: AddText reads _CmdHeader.ClipRect (not _ClipRectStack.back())
    // to decide per-glyph culling. Save & restore it alongside the stack so that
    // text drawn at SetCursorScreenPos({0,0}) isn't culled by the inner child's
    // original clip rect.
    ImVec4 m_cmdHeaderClipRect = ImVec4(0.0f, 0.0f, 0.0f, 0.0f);

    void* m_ctxIOUserData = nullptr;

    // Canvas frame info exposed to Widget tooltip code via global pointer
    // (replaces the IO.UserData aliasing hack)
    ActiveCanvasFrameInfo m_canvasFrameInfo;

    size_t m_currentLod = 0;

    // Non-rendering Label widget inside the CanvasFrame. This is a sort of
    // placeholder widget. This Label widget won’t actually be visible or
    // participate in any rendering process. Its purpose is to hold onto the
    // font resources we need.
    // The problem we're fixing here is that whenever all nodes get deleted,
    // omni.ui also deleted all font resources. This meant that when we wanted
    // to create nodes again, we also had to recreate all those font resources -
    // not very efficient!
    std::shared_ptr<Label> m_fontBuffer;

    // That's how the pan is initiated
    uint32_t m_panMouseButton;
    KeyboardModifierFlags m_panKeyFlag;

    // That's how the zoom is initiated
    uint32_t m_zoomMouseButton;
    KeyboardModifierFlags m_zoomKeyFlag;

    // focus position for mouse move scrolling zoom
    ImVec2 m_focusPosition;

    // The real zoom, we need it to make the zoom smooth when scrolling with mouse.
    float m_zoomSmooth = -1.f;

    // only mouse click inside the CanvasFrame considers the signal of checking the pan and zoom
    bool m_panStarted = false;
    // True when the user pans the child. We need it to know if the user did it on the previous frame to be able to
    // continue panning outside of the widget.
    bool m_panActive = false;

    bool m_zoomStarted = false;
    // flag to show whether the mouse moving zoom is active
    bool m_zoomMoveActive = false;

    void saveImGuiState()
    {
        auto* ctx = ImGui::GetCurrentContext();

        m_ctxIOMousePosX = ctx->IO.MousePos.x;
        m_ctxIOMousePosY = ctx->IO.MousePos.y;
        m_ctxIOMouseDeltaX = ctx->IO.MouseDelta.x;
        m_ctxIOMouseDeltaY = ctx->IO.MouseDelta.y;
        m_ctxMouseViewportPosX = ctx->MouseViewport->Pos.x;
        m_ctxMouseViewportPosY = ctx->MouseViewport->Pos.y;
        m_ctxMouseViewportSizeX = ctx->MouseViewport->Size.x;
        m_ctxMouseViewportSizeY = ctx->MouseViewport->Size.y;
        m_ctxCurrentWindowPosX = ctx->CurrentWindow->Pos.x;
        m_ctxCurrentWindowPosY = ctx->CurrentWindow->Pos.y;
        m_ctxCurrentWindowSizeX = ctx->CurrentWindow->Size.x;
        m_ctxCurrentWindowSizeY = ctx->CurrentWindow->Size.y;
        m_ctxCurrentWindowClipRectMinX = ctx->CurrentWindow->ClipRect.Min.x;
        m_ctxCurrentWindowClipRectMinY = ctx->CurrentWindow->ClipRect.Min.y;
        m_ctxCurrentWindowClipRectMaxX = ctx->CurrentWindow->ClipRect.Max.x;
        m_ctxCurrentWindowClipRectMaxY = ctx->CurrentWindow->ClipRect.Max.y;
        auto* drawList = ImGui::GetWindowDrawList();
        m_clipRectStack = drawList->_ClipRectStack;
        m_cmdHeaderClipRect = drawList->_CmdHeader.ClipRect;

        m_ctxIOUserData = ctx->IO.UserData;
    }

    void changeImGuiState(ImVec2 pan, float scale)
    {
        auto* ctx = ImGui::GetCurrentContext();

        float invScale = 1.0f / scale;

        ctx->IO.MousePos.x -= pan.x;
        ctx->IO.MousePos.y -= pan.y;
        ctx->MouseViewport->Pos.x -= pan.x;
        ctx->MouseViewport->Pos.y -= pan.y;

        ctx->CurrentWindow->Pos.x -= pan.x;
        ctx->CurrentWindow->Pos.y -= pan.y;

        // Don't clip the window
        ctx->CurrentWindow->ClipRect.Min.x = -kFloatMax;
        ctx->CurrentWindow->ClipRect.Max.x = kFloatMax;
        ctx->CurrentWindow->ClipRect.Min.y = -kFloatMax;
        ctx->CurrentWindow->ClipRect.Max.y = kFloatMax;

        ctx->IO.MousePos.x *= invScale;
        ctx->IO.MousePos.y *= invScale;
        ctx->IO.MouseDelta.x *= invScale;
        ctx->IO.MouseDelta.y *= invScale;
        ctx->MouseViewport->Pos.x *= invScale;
        ctx->MouseViewport->Pos.y *= invScale;
        ctx->MouseViewport->Size.x *= invScale;
        ctx->MouseViewport->Size.y *= invScale;
        ctx->CurrentWindow->Pos.x *= invScale;
        ctx->CurrentWindow->Pos.y *= invScale;
        ctx->CurrentWindow->Size.x *= invScale;
        ctx->CurrentWindow->Size.y *= invScale;

        // Don't clip anything. Under ImGui 1.92.7 AddText reads _CmdHeader.ClipRect
        // (not _ClipRectStack.back()) for per-glyph culling, so both need updating.
        auto* drawList = ImGui::GetWindowDrawList();
        for (auto& c : drawList->_ClipRectStack)
        {
            c.x = -kFloatMax;
            c.y = -kFloatMax;
            c.z = kFloatMax;
            c.w = kFloatMax;
        }
        drawList->_CmdHeader.ClipRect = ImVec4(-kFloatMax, -kFloatMax, kFloatMax, kFloatMax);
        drawList->_OnChangedClipRect();

        // Store cached mouse position for Widget tooltip correction
        m_canvasFrameInfo.cachedMousePosX = m_ctxIOMousePosX;
        m_canvasFrameInfo.cachedMousePosY = m_ctxIOMousePosY;
        // Note: IO.UserData is kept for backward compatibility with any code
        // that reads it directly. The global g_activeCanvasFrameData is the
        // preferred way to access this data (see CanvasFrameGuard.h).
        ctx->IO.UserData = this;
    }

    void restoreImGuiState()
    {
        auto* ctx = ImGui::GetCurrentContext();

        ctx->IO.MousePos.x = m_ctxIOMousePosX;
        ctx->IO.MousePos.y = m_ctxIOMousePosY;
        ctx->IO.MouseDelta.x = m_ctxIOMouseDeltaX;
        ctx->IO.MouseDelta.y = m_ctxIOMouseDeltaY;
        ctx->MouseViewport->Pos.x = m_ctxMouseViewportPosX;
        ctx->MouseViewport->Pos.y = m_ctxMouseViewportPosY;
        ctx->MouseViewport->Size.x = m_ctxMouseViewportSizeX;
        ctx->MouseViewport->Size.y = m_ctxMouseViewportSizeY;
        ctx->CurrentWindow->Pos.x = m_ctxCurrentWindowPosX;
        ctx->CurrentWindow->Pos.y = m_ctxCurrentWindowPosY;
        ctx->CurrentWindow->Size.x = m_ctxCurrentWindowSizeX;
        ctx->CurrentWindow->Size.y = m_ctxCurrentWindowSizeY;
        ctx->CurrentWindow->ClipRect.Min.x = m_ctxCurrentWindowClipRectMinX;
        ctx->CurrentWindow->ClipRect.Min.y = m_ctxCurrentWindowClipRectMinY;
        ctx->CurrentWindow->ClipRect.Max.x = m_ctxCurrentWindowClipRectMaxX;
        ctx->CurrentWindow->ClipRect.Max.y = m_ctxCurrentWindowClipRectMaxY;
        auto* drawList = ImGui::GetWindowDrawList();
        drawList->_ClipRectStack = m_clipRectStack;
        drawList->_CmdHeader.ClipRect = m_cmdHeaderClipRect;
        drawList->_OnChangedClipRect();

        ctx->IO.UserData = m_ctxIOUserData;
    }
};


/**
 * @brief Sets the clipping rectangle for the given draw list.
 *
 * The function ensures that the clipping rectangles (both for individual commands
 * and for the overall draw list) do not get reversed, which can cause graphical
 * artifacts on some rendering backends like Vulkan.
 */
static void _setDrawListClipping(ImDrawList* drawList, ImVec4 clipping)
{
    // Process each command in the draw list's command buffer.
    for (auto& command : drawList->CmdBuffer)
    {
        // Intersect the existing clipping rectangle with the provided clipping.
        command.ClipRect.x = std::max(command.ClipRect.x, clipping.x);
        command.ClipRect.y = std::max(command.ClipRect.y, clipping.y);
        command.ClipRect.z = std::min(command.ClipRect.z, clipping.z);
        command.ClipRect.w = std::min(command.ClipRect.w, clipping.w);

        // Ensure the clipping rect is not reversed.
        // If the z-value (end point) is before the x-value (start point), set it equal to the x-value.
        command.ClipRect.z = std::max(command.ClipRect.x, command.ClipRect.z);
        // Similarly, ensure the w-value (end point) isn't before the y-value (start point).
        command.ClipRect.w = std::max(command.ClipRect.y, command.ClipRect.w);
    }

    // Process each item in the draw list's clipping rectangle stack.
    for (auto& clip : drawList->_ClipRectStack)
    {
        // Intersect the existing clipping rectangle with the provided clipping.
        clip.x = std::max(clip.x, clipping.x);
        clip.y = std::max(clip.y, clipping.y);
        clip.z = std::min(clip.z, clipping.z);
        clip.w = std::min(clip.w, clipping.w);

        // Ensure the clipping rect is not reversed.
        // If the z-value (end point) is before the x-value (start point), set it equal to the x-value.
        clip.z = std::max(clip.x, clip.z);
        // Similarly, ensure the w-value (end point) isn't before the y-value (start point).
        clip.w = std::max(clip.y, clip.w);
    }
}

/**
 * @brief Moves all the positions of the given draw list by applying a delta
 * translation and scaling
 *
 * @param drawList Pointer to an ImDrawList object representing the list of
 *                 drawing commands to be transformed
 * @param delta Vector representing the translation to be applied to the
 *              positions in the draw list
 * @param scale Scalar representing the scaling factor to be applied to the
 *              positions in the draw list
 */
static void _moveDrawList(ImDrawList* drawList, ImVec2 delta, float scale)
{
    // If delta is zero, no need to apply any transformation
    if (delta.x == 0.0f && delta.y == 0.0f)
    {
        return;
    }

    // Transform the vertices in the VtxBuffer by scaling and translating them
    for (auto& vertex : drawList->VtxBuffer)
    {
        vertex.pos.x *= scale;
        vertex.pos.y *= scale;

        vertex.pos.x += delta.x;
        vertex.pos.y += delta.y;
    }

    // Transform the clipping rectangles in the CmdBuffer by scaling and
    // translating them
    for (auto& command : drawList->CmdBuffer)
    {
        auto& clippingRect = command.ClipRect;

        clippingRect.x *= scale;
        clippingRect.y *= scale;
        clippingRect.z *= scale;
        clippingRect.w *= scale;

        clippingRect.x += delta.x;
        clippingRect.y += delta.y;
        clippingRect.z += delta.x;
        clippingRect.w += delta.y;
    }

    // Transform the clipping rectangles in the _ClipRectStack by scaling and
    // translating them
    for (auto clippingRect : drawList->_ClipRectStack)
    {
        clippingRect.x *= scale;
        clippingRect.y *= scale;
        clippingRect.z *= scale;
        clippingRect.w *= scale;

        clippingRect.x += delta.x;
        clippingRect.y += delta.y;
        clippingRect.z += delta.x;
        clippingRect.w += delta.y;
    }
}

/**
 * @brief Add the content of the draw lists of all the child windows to the
 * given draw list
 */
static void _moveWindow(ImGuiWindow* window, ImVec2 delta, float scale)
{
    _moveDrawList(window->DrawList, delta, scale);

    for (int i = 0; i < window->DC.ChildWindows.Size; i++)
    {
        ImGuiWindow* child = window->DC.ChildWindows[i];

        // Clipped children may have been marked not active
        if (child && child->Active && !child->Hidden)
        {
            // This is to patch hovering
            child->OuterRectClipped.Min.x *= scale;
            child->OuterRectClipped.Min.y *= scale;
            child->OuterRectClipped.Max.x *= scale;
            child->OuterRectClipped.Max.y *= scale;

            child->OuterRectClipped.Min.x += delta.x;
            child->OuterRectClipped.Min.y += delta.y;
            child->OuterRectClipped.Max.x += delta.x;
            child->OuterRectClipped.Max.y += delta.y;

            child->OuterRectClipped.ClipWith(window->OuterRectClipped);

            _moveWindow(child, delta, scale);
        }
    }
}

static void _makeClippingRectLikeParent(ImGuiWindow* window)
{
    // Iterate over all child windows of the given parent window
    for (int i = 0; i < window->DC.ChildWindows.Size; i++)
    {
        ImGuiWindow* child = window->DC.ChildWindows[i];

        // If the child window is active and not hidden
        // Clipped children may have been marked not active
        if (child && child->Active && !child->Hidden)
        {
            // Set the clipping rectangle of the child window's draw list to be
            // the same as the parent window's
            _setDrawListClipping(child->DrawList, window->DrawList->_ClipRectStack.back());

            // Recursively call this function on the child window
            _makeClippingRectLikeParent(child);
        }
    }
}


CanvasFrame::CanvasFrame()
    : Frame(new CanvasFrameData)
{
    // Default pan is with middle mouse button with no keyboard
    this->setPanKeyShortcut(2, 0);
    // Default zoom is with middle mouse button with no keyboard
    this->setZoomKeyShortcut(2, 0);
    this->setZoomChangedFn([this](const float& zoom) {
        if (this->isCompatibility())
        {
            this->forceWidthDirty(SizeDirtyReason::eChildDirty);
            this->forceHeightDirty(SizeDirtyReason::eChildDirty);
            this->forceRasterDirty(BakeDirtyReason::eContentChanged);
        }
    });
    this->_setScaleChangedFn([this](const float& scale) {
        if (this->isCompatibility())
        {
            this->forceWidthDirty(SizeDirtyReason::eChildDirty);
            this->forceHeightDirty(SizeDirtyReason::eChildDirty);
        }
    });
}

CanvasFrame::~CanvasFrame() = default;

/**
 * @brief Returns a valid zoom value within the range of minimum and maximum
 * zoom levels.
 */
float CanvasFrame::_getZoom(float zoom)
{
    return std::max(std::min(zoom, this->getZoomMax()), this->getZoomMin());
}

void CanvasFrame::setComputedContentWidth(float width)
{
    auto& data = _getData<CanvasFrameData>();
    if (data.m_zoomSmooth < 0.0f)
    {
        data.m_zoomSmooth = _getZoom(this->getZoom());
    }

    if (this->isCompatibility())
    {
        this->setScale(data.m_zoomSmooth);
    }
    else
    {
        this->setScale(1.0f);
        this->setCanvasZoom(data.m_zoomSmooth);
    }

    // The content of the canvas is scaled.
    Frame::setComputedContentWidth(width * data.m_zoomSmooth);

    // The widget itself is not scaled additionaly.
    Widget::setComputedContentWidth(width);
}

void CanvasFrame::setComputedContentHeight(float height)
{
    auto& data = _getData<CanvasFrameData>();
    if (data.m_zoomSmooth < 0.0f)
    {
        data.m_zoomSmooth = _getZoom(this->getZoom());
    }

    if (this->isCompatibility())
    {
        this->setScale(data.m_zoomSmooth);
    }
    else
    {
        this->setScale(1.0f);
        this->setCanvasZoom(data.m_zoomSmooth);
    }

    // The content of the canvas is scaled.
    Frame::setComputedContentHeight(height * data.m_zoomSmooth);

    // The widget itself is not scaled additionaly.
    Widget::setComputedContentHeight(height);
}

float CanvasFrame::screenToCanvasX(float x) const
{
    float xx = x - this->getScreenPositionX();

    if (this->isCompatibility())
    {
        return xx / this->getDpiScale() - this->getPanX() / this->_getScale();
    }
    else
    {
        // We don't use scale anymore. We scale DrawList.
        auto& data = _getData<CanvasFrameData>();
        return (xx / this->getDpiScale() - this->getPanX()) / data.m_zoomSmooth;
    }
}

float CanvasFrame::screenToCanvasY(float y) const
{
    float yy = y - this->getScreenPositionY();

    if (this->isCompatibility())
    {
        return yy / this->getDpiScale() - this->getPanY() / this->_getScale();
    }
    else
    {
        // We don't use scale anymore. We scale DrawList.
        auto& data = _getData<CanvasFrameData>();
        return (yy / this->getDpiScale() - this->getPanY()) / data.m_zoomSmooth;
    }
}

void CanvasFrame::setPanKeyShortcut(uint32_t mouseButton, KeyboardModifierFlags keyFlag)
{
    auto& data = _getData<CanvasFrameData>();
    data.m_panMouseButton = mouseButton;
    data.m_panKeyFlag = keyFlag;
}

void CanvasFrame::setZoomKeyShortcut(uint32_t mouseButton, KeyboardModifierFlags keyFlag)
{
    auto& data = _getData<CanvasFrameData>();
    data.m_zoomMouseButton = mouseButton;
    data.m_zoomKeyFlag = keyFlag;
}

void CanvasFrame::_drawContent(float elapsedTime)
{
    if (this->isCompatibility())
    {
        this->_drawContentCompatibility(elapsedTime);
        return;
    }

    // See m_fontBuffer definition for comments
    auto& data = _getData<CanvasFrameData>();
    if (!data.m_fontBuffer)
    {
        OMNIKIT_WITH_CONTAINER(nullptr)
        {
            data.m_fontBuffer = Label::create("A");
            data.m_fontBuffer->setParent(this);
            data.m_fontBuffer->setComputedContentWidth(1.0f);
            data.m_fontBuffer->setComputedContentHeight(1.0f);
        }
    }

    if (data.m_zoomSmooth < 0.0f)
    {
        data.m_zoomSmooth = _getZoom(this->getZoom());
    }

    uint32_t color;
    int pushedColorCounter = 0;

    if (this->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &color))
    {
        // Push and Pop are very cheap in ImGui because ImVector never decreases capacity.
        ImGui::PushStyleColor(ImGuiCol_ChildBg, color);
        pushedColorCounter++;
    }

    auto* ctx = ImGui::GetCurrentContext();

    const auto& name = this->getName();

    // Use the name as ImGui ID if possible.
    if (!name.empty())
    {
        ImGui::PushID(name.c_str());
    }
    else
    {
        ImGui::PushID(this);
    }

    ImGuiWindowFlags flags = ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse;

    // Create a window with the specified size.
    ImGui::BeginChild("", { this->getComputedContentWidth(), this->getComputedContentHeight() }, false, flags);

    // When it's left mouse button, the user can not pan when the mouse hovers
    // nodes. When it's the other button, it's possible to pan in the same case.
    bool hovered =
        ImGui::IsWindowHovered(data.m_panMouseButton == 0 ? ImGuiHoveredFlags_None : ImGuiHoveredFlags_ChildWindows);

    float dpiScale = Workspace::getDpiScale();
    float dpiScaleInv = 1.0f / dpiScale;

    ImGui::BeginChild("", { this->getComputedContentWidth(), this->getComputedContentHeight() }, false, flags);

    // Pan
    // make sure the pan only starts when the click is inside the CanvasFrame, we don't use
    // m_isClicked[m_panMouseButton] since the hovered in the Widget.cpp is not working for CanvasFrame
    bool isPanMouseClicked = ImGui::IsMouseClicked(data.m_panMouseButton) && hovered;
    if (isPanMouseClicked)
    {
        data.m_panStarted = true;
    }

    {
        // Using data.m_panActive to determine if the user already drags it. He can continue dragging outside of this window.
        data.m_panActive = this->isDraggable() && (data.m_panActive || hovered) && isPressed(data.m_panMouseButton) && data.m_panStarted;

        // Check if we need a key modifier to pan.
        if (data.m_panActive && data.m_panKeyFlag)
        {
            const ImGuiIO& io = ImGui::GetIO();
            KeyboardModifierFlags modifiers = (io.KeyAlt ? kKeyModAlt : 0) |
                                                           (io.KeyShift ? kKeyModShift : 0) |
                                                           (io.KeyCtrl ? kKeyModCtrl : 0) |
                                                           (io.KeySuper ? kKeyModSuper : 0);
            data.m_panActive = (modifiers & data.m_panKeyFlag) == data.m_panKeyFlag;
        }

        if (data.m_panActive)
        {
            const ImGuiIO& io = ImGui::GetIO();
            const auto& mouseDelta = io.MouseDelta;

            this->setPanX(this->getPanX() + mouseDelta.x * dpiScaleInv);
            this->setPanY(this->getPanY() + mouseDelta.y * dpiScaleInv);
        }
        else
        {
            // finish panning
            data.m_panStarted = false;
        }
    }

    // Zoom
    float zoomMultiplier = 1.0f;
    bool isZooming = false;
    if (!data.m_panActive && this->isDraggable() && hovered)
    {
        const ImGuiIO& io = ImGui::GetIO();

        // make sure the zoom only starts when the click is inside the CanvasFrame, we don't use
        // m_isClicked[m_zoomMouseButton] since the hovered in the Widget.cpp is not working for CanvasFrame
        bool isZoomMouseClicked = ImGui::IsMouseClicked(data.m_zoomMouseButton) && hovered;
        if (isZoomMouseClicked)
        {
            data.m_zoomStarted = true;
        }

        if (data.m_zoomStarted && isPressed(data.m_zoomMouseButton))
        {
            // if m_zoomKeyFlag == 0, modifierActive is already true
            // need to allow set like set_zoom_key_shortcut(1, 0)
            bool modifierActive = !data.m_zoomKeyFlag;
            // check the modifer if there is any
            if (data.m_zoomKeyFlag)
            {
                KeyboardModifierFlags modifiers = (io.KeyAlt ? kKeyModAlt : 0) |
                                                            (io.KeyShift ? kKeyModShift : 0) |
                                                            (io.KeyCtrl ? kKeyModCtrl : 0) |
                                                            (io.KeySuper ? kKeyModSuper : 0);
                modifierActive = (modifiers & data.m_zoomKeyFlag) == data.m_zoomKeyFlag;
            }
            // zoom with mouse press
            if (modifierActive)
            {
                const auto& mouseDelta = io.MouseDelta;
                if (mouseDelta.x != 0.0f)
                {
                    constexpr float zoomSensitivity = 0.0025f;
                    zoomMultiplier = powf(2.0f, mouseDelta.x * zoomSensitivity);
                }
            }

            // only record the m_focusPosition when mouse move starts
            if (!data.m_zoomMoveActive)
            {
                data.m_focusPosition = io.MousePos;
                data.m_zoomMoveActive = true;
            }
        }
        else
        {
            data.m_zoomStarted = false;
            if (data.m_zoomKeyFlag)
            {
                data.m_zoomMoveActive = false;
            }
        }

        // mouse wheel scrolling to zoom
        float wheel = io.MouseWheel;
        if (wheel != 0.0f)
        {
            // TODO: the precision problems are possible because of float
            constexpr float zoomSensitivity = 0.25f;
            zoomMultiplier *= powf(2.0f, wheel * zoomSensitivity);
            data.m_focusPosition = io.MousePos;
            data.m_zoomMoveActive = false;
        }

        if (zoomMultiplier != 1.0f)
        {
            this->setZoom(_getZoom(this->getZoom() * zoomMultiplier));
            isZooming = true;
        }
    }

    // Keep ImGui
    data.saveImGuiState();

    // Change the ImGui internal state
    auto cursor = ImGui::GetCursorScreenPos();
    ImVec2 cursorWithOffset{ cursor.x + this->getPanX() * dpiScale, cursor.y + this->getPanY() * dpiScale };
    data.changeImGuiState(cursorWithOffset, data.m_zoomSmooth);

    // Set global canvas frame data for Widget tooltip code (replaces IO.UserData hack)
    CanvasFrameGuard canvasGuard(&data.m_canvasFrameInfo);

    // Put cursor to origin
    ImGui::SetCursorScreenPos({0.0f, 0.0f});

    // Draw child
    Frame::_drawContent(elapsedTime);

    _moveWindow(ctx->CurrentWindow, cursorWithOffset, data.m_zoomSmooth);

    ImGui::SetCursorScreenPos(cursor);

    // Restore ImGui state
    data.restoreImGuiState();

    ImGui::EndChild();

    // Set the clipping rectangle of the child window's draw list to be the same
    // as the parent window
    _makeClippingRectLikeParent(ctx->CurrentWindow);

    ImGui::EndChild();
    ImGui::PopID();

    ImGui::PopStyleColor(pushedColorCounter);

    // Smooth zoom
    float zoom = _getZoom(this->getZoom());
    if (zoom != data.m_zoomSmooth)
    {
        // Initialize the LOD variables and a vector to store the sorted
        // thresholds
        size_t lodBefore = 0;
        size_t lodAfter = 0;

        // If the new CanvasFrame, calculate the LOD based on the visible
        // thresholds based on visibleMin and visibleMax properties
        if (!this->isCompatibility())
        {
            lodBefore = data.m_currentLod;
        }

        // If the zoom level is capped by min and max or smooth zooming is enabled, adjust the zoom level
        if (this->isSmoothZoom() || zoom == this->getZoomMax() || zoom == this->getZoomMin())
        {
            // Bigget number - slower smooth scrolling
            constexpr float speed = 0.03f;

            // Calculate the zoom multiplier based on the current zoom level
            // considering the time
            if (zoom < data.m_zoomSmooth)
            {
                zoomMultiplier = std::max(powf(speed, elapsedTime), zoom / data.m_zoomSmooth);
            }
            else
            {
                zoomMultiplier = std::min(1.0f / powf(speed, elapsedTime), zoom / data.m_zoomSmooth);
            }

            // Update the smoothed zoom level
            data.m_zoomSmooth *= zoomMultiplier;
        }
        else
        {
            // If smooth zooming is disabled, set the smoothed zoom level to the
            // current zoom level
            data.m_zoomSmooth = zoom;
        }

        // If zooming is in progress or smooth zooming is enabled, adjust the
        // pan position
        if (isZooming || this->isSmoothZoom())
        {
            // Zoom relative to the focus position to avoid jittering.
            const ImGuiIO& io = ImGui::GetIO();
            ImVec2 directionToCenter{ data.m_focusPosition.x - cursorWithOffset.x, data.m_focusPosition.y - cursorWithOffset.y };

            // Update the pan position based on the direction and zoom
            // multiplier
            this->setPanX(this->getPanX() + directionToCenter.x * (1.0f - zoomMultiplier) * dpiScaleInv);
            this->setPanY(this->getPanY() + directionToCenter.y * (1.0f - zoomMultiplier) * dpiScaleInv);
        }

        // If the new CanvasFrame, calculate the new LOD based on the updated
        // zoom level
        if (!this->isCompatibility())
        {
            // Find the position of the threshold above the updated zoom level
            lodAfter = this->_getCurrentLod(data.m_zoomSmooth);
        }

        // If the LOD has changed, rebuild all the child rasters
        if (lodBefore != lodAfter)
        {
            data.m_currentLod = lodAfter;

            // It's only important to set it when the LOD level is changed. No
            // need to set it every frame because it involves iteration.
            this->setCanvasZoom(data.m_zoomSmooth);

            this->forceRasterDirty(BakeDirtyReason::eLodDirty);
        }
    }
}

bool CanvasFrame::_isParentCanvasFrame() const
{
    // If it's compatibility mode, the child widgets are not in scalable
    // envirionment.
    return !this->isCompatibility();
}

void CanvasFrame::_drawContentCompatibility(float elapsedTime)
{
    auto& data = _getData<CanvasFrameData>();
    if (data.m_zoomSmooth < 0.0f)
    {
        data.m_zoomSmooth = _getZoom(this->getZoom());
    }

    uint32_t color;
    int pushedColorCounter = 0;

    if (this->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &color))
    {
        // Push and Pop are very cheap in ImGui because ImVector never decreases capacity.
        ImGui::PushStyleColor(ImGuiCol_ChildBg, color);
        pushedColorCounter++;
    }

    const auto& name = this->getName();

    // Use the name as ImGui ID if possible.
    if (!name.empty())
    {
        ImGui::PushID(name.c_str());
    }
    else
    {
        ImGui::PushID(this);
    }

    ImGuiWindowFlags flags = ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse;

    // Create a window with the specified size.
    ImGui::BeginChild("", { this->getComputedContentWidth(), this->getComputedContentHeight() }, false, flags);

    // Set the font scale of the window. It's important to set the font scale of the previous frame. Because the zoom
    // will be applied to widgets the next frame.
    // ImGui::SetWindowFontScale(data.m_zoomSmooth);

    // When it's left mouse button, the user can not pan when the mouse hovers
    // nodes. When it's the other button, it's possible to pan in the same case.
    bool hovered =
        ImGui::IsWindowHovered(data.m_panMouseButton == 0 ? ImGuiHoveredFlags_None : ImGuiHoveredFlags_ChildWindows);

    // Pan
    // make sure the pan only starts when the click is inside the CanvasFrame, we don't use
    // m_isClicked[m_panMouseButton] since the hovered in the Widget.cpp is not working for CanvasFrame
    bool isPanMouseClicked = ImGui::IsMouseClicked(data.m_panMouseButton) && hovered;
    if (isPanMouseClicked)
    {
        data.m_panStarted = true;
    }

    // Using data.m_panActive to determine if the user already drags it. He can continue dragging outside of this window.
    data.m_panActive = this->isDraggable() && (data.m_panActive || hovered) && isPressed(data.m_panMouseButton) && data.m_panStarted;

    // Check if we need a key modifier to pan.
    if (data.m_panActive && data.m_panKeyFlag)
    {
        const ImGuiIO& io = ImGui::GetIO();
        KeyboardModifierFlags modifiers = (io.KeyAlt ? kKeyModAlt : 0) |
                                                       (io.KeyShift ? kKeyModShift : 0) |
                                                       (io.KeyCtrl ? kKeyModCtrl : 0) |
                                                       (io.KeySuper ? kKeyModSuper : 0);
        data.m_panActive = (modifiers & data.m_panKeyFlag) == data.m_panKeyFlag;
    }

    float dpiScale = Workspace::getDpiScale();
    float dpiScaleInv = 1.0f / dpiScale;

    if (data.m_panActive)
    {
        const ImGuiIO& io = ImGui::GetIO();
        const auto& mouseDelta = io.MouseDelta;

        this->setPanX(this->getPanX() + mouseDelta.x * dpiScaleInv);
        this->setPanY(this->getPanY() + mouseDelta.y * dpiScaleInv);
    }
    else
    {
        // finish panning
        data.m_panStarted = false;
    }

    auto cursor = ImGui::GetCursorScreenPos();
    auto cursorWithOffset = cursor;
    cursorWithOffset.x += this->getPanX() * dpiScale;
    cursorWithOffset.y += this->getPanY() * dpiScale;

    // Zoom
    float zoomMultiplier = 1.0f;
    bool isZooming = false;
    if (!data.m_panActive && this->isDraggable() && hovered)
    {
        const ImGuiIO& io = ImGui::GetIO();

        // make sure the zoom only starts when the click is inside the CanvasFrame, we don't use
        // m_isClicked[m_zoomMouseButton] since the hovered in the Widget.cpp is not working for CanvasFrame
        bool isZoomMouseClicked = ImGui::IsMouseClicked(data.m_zoomMouseButton) && hovered;
        if (isZoomMouseClicked)
        {
            data.m_zoomStarted = true;
        }

        // mouse pressed and move to zoom
        if (data.m_zoomStarted && isPressed(data.m_zoomMouseButton))
        {
            // if m_zoomKeyFlag == 0, modifierActive is already true
            // need to allow set like set_zoom_key_shortcut(1, 0)
            bool modifierActive= !data.m_zoomKeyFlag;
            // check the modifer if there is any
            if (data.m_zoomKeyFlag)
            {
                KeyboardModifierFlags modifiers = (io.KeyAlt ? kKeyModAlt : 0) |
                                                            (io.KeyShift ? kKeyModShift : 0) |
                                                            (io.KeyCtrl ? kKeyModCtrl : 0) |
                                                            (io.KeySuper ? kKeyModSuper : 0);
                modifierActive = (modifiers & data.m_zoomKeyFlag) == data.m_zoomKeyFlag;
            }
            // zoom with mouse press
            if (modifierActive)
            {
                const auto& mouseDelta = io.MouseDelta;
                if (mouseDelta.x != 0.0f)
                {
                    constexpr float zoomSensitivity = 0.0025f;
                    zoomMultiplier = powf(2.0f, mouseDelta.x * zoomSensitivity);
                }
            }

            // only record the m_focusPosition when mouse move starts
            if (!data.m_zoomMoveActive)
            {
                data.m_focusPosition = io.MousePos;
                data.m_zoomMoveActive = true;
            }
        }
        else
        {
            data.m_zoomStarted = false;
            if (data.m_zoomKeyFlag)
            {
                data.m_zoomMoveActive = false;
            }
        }

        // mouse wheel scrolling to zoom
        float wheel = io.MouseWheel;
        if (wheel != 0.0f)
        {
            // TODO: the precision problems are possible because of float
            constexpr float zoomSensitivity = 0.25f;
            zoomMultiplier *= powf(2.0f, wheel * zoomSensitivity);
            data.m_focusPosition = io.MousePos;
            data.m_zoomMoveActive = false;
        }

        if (zoomMultiplier != 1.0f)
        {
            this->setZoom(_getZoom(this->getZoom() * zoomMultiplier));
            isZooming = true;
        }
    }

    ImGui::SetCursorScreenPos(cursorWithOffset);

    // Draw child
    Frame::_drawContent(elapsedTime);

    ImGui::SetCursorScreenPos(cursor);

    ImGui::EndChild();
    ImGui::PopID();

    ImGui::PopStyleColor(pushedColorCounter);

    // Smooth zoom
    float zoom = _getZoom(this->getZoom());
    if (zoom != data.m_zoomSmooth)
    {
        // if the zoom is capped by min and max, we need to make it smooth to avoid jittering
        if (this->isSmoothZoom() || zoom == this->getZoomMax() || zoom == this->getZoomMin())
        {
            // Bigget number - slower smooth scrolling
            constexpr float speed = 0.03f;
            if (zoom < data.m_zoomSmooth)
            {
                zoomMultiplier = std::max(powf(speed, elapsedTime), zoom / data.m_zoomSmooth);
            }
            else
            {
                zoomMultiplier = std::min(1.0f / powf(speed, elapsedTime), zoom / data.m_zoomSmooth);
            }
            data.m_zoomSmooth *= zoomMultiplier;
        }
        else
        {
            data.m_zoomSmooth = zoom;
        }

        if (isZooming || this->isSmoothZoom())
        {
            // Zoom relative to the focus position to avoid jittering.
            const ImGuiIO& io = ImGui::GetIO();
            ImVec2 directionToCenter{ data.m_focusPosition.x - cursorWithOffset.x, data.m_focusPosition.y - cursorWithOffset.y };

            this->setPanX(this->getPanX() + directionToCenter.x * (1.0f - zoomMultiplier) * dpiScaleInv);
            this->setPanY(this->getPanY() + directionToCenter.y * (1.0f - zoomMultiplier) * dpiScaleInv);
        }
    }

    this->setScale(data.m_zoomSmooth);
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
