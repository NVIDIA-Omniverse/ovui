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
#include "platform/CachedSetting.h"

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/Frame.h>
#include <omni/ui/HStack.h>
#include <omni/ui/Inspector.h>
#include <omni/ui/Label.h>
#include <omni/ui/Menu.h>
#include <omni/ui/MenuBar.h>
#include <omni/ui/MenuDelegate.h>
#include <omni/ui/MenuItem.h>
#include <omni/ui/RasterHelper.h>

#include <cmath>
#include <iterator>
#include <unordered_set>

OMNIUI_NAMESPACE_OPEN_SCOPE

// Debug draw constants
constexpr uint32_t kDebugDrawColor = 0x11ffff00;
static constexpr char kDebugDrawSettingsPath[] = "/exts/omni.ui/raster/draw_debug";
static constexpr char kDelaySettingsPath[] = "/exts/omni.ui/raster/delay";
constexpr uint32_t kWindowFlags_Raster = 1 << 30;

struct ImDrawListDeleter
{
    void operator()(ImDrawList* ptr) const
    {
        IM_DELETE(ptr);
    }
};

struct RasterHelperPrivate
{
    std::vector<std::unique_ptr<ImDrawList, ImDrawListDeleter>> m_drawList;
    size_t m_drawListIndex = 0;
    ImVec2 m_drawListPosition;
    std::vector<bool> m_drawListDirty;
    bool m_lastHovered = false;
    float m_lastWidth = 0.0f;
    float m_lastHeight = 0.0f;
    uint32_t m_framesToBake = UINT32_MAX;
    uint8_t m_mousePressedInsideFrame = 0;
    bool m_editingMode = false;

    Widget* m_widget;

    bool m_needSeparateWindow;
    bool m_isCaptureRaster;
    ImVec2 m_cursor;
    ImVec2 m_childWindowSize;
    ImVec2 m_childWindowPos;

    bool m_invalidatedOnDemand = true;

    ImGuiWindow* m_bakeWindow = nullptr;
};

static bool _isDebugDraw()
{
    static CachedBoolSetting debugDraw(kDebugDrawSettingsPath, false);
    return debugDraw.get();
}

static int32_t _getRasterDealy()
{
    static CachedIntSetting rasterDelay(kDelaySettingsPath, 2);
    return rasterDelay.get();
}

/**
 * @brief Moves all the positions of the given draw list
 */
static void _moveDrawList(ImDrawList* drawList, ImVec2 delta)
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

/**
 * @brief Adds the content of the source draw list to the destanation
 */
static void _mergeDrawLists(ImDrawList* dst, ImDrawList* src)
{
    if (src->CmdBuffer.empty())
    {
        return;
    }

    // Remove trailing command if unused
    ImDrawCmd& last_cmd = src->CmdBuffer.back();
    if (last_cmd.ElemCount == 0 && last_cmd.UserCallback == NULL)
    {
        src->CmdBuffer.pop_back();
        if (src->CmdBuffer.empty())
        {
            return;
        }
    }

    auto vtxBufferSize = dst->VtxBuffer.size();
    auto idxBufferSize = dst->IdxBuffer.size();

    // Cmd
    for (const auto& buffer : src->CmdBuffer)
    {
        dst->CmdBuffer.push_back(buffer);
        dst->CmdBuffer.back().VtxOffset += vtxBufferSize;
        dst->CmdBuffer.back().IdxOffset += idxBufferSize;
    }

    // Idx
    std::transform(src->IdxBuffer.begin(), src->IdxBuffer.end(), std::back_inserter(dst->IdxBuffer),
                   [vtxBufferSize](ImGuiID i) { return i + vtxBufferSize; });

    // Vtx
    std::copy(src->VtxBuffer.begin(), src->VtxBuffer.end(), std::back_inserter(dst->VtxBuffer));

    // Flags
    if (dst->Flags == ImDrawListFlags_None)
    {
        dst->Flags = src->Flags;
    }
}

/**
 * @brief Add the content of the draw lists of all the child windows to the
 * given draw list
 */
static void _mergeChildrenWindowsToDrawList(ImDrawList* drawList, const ImGuiWindow* window)
{
    for (int i = 0; i < window->DC.ChildWindows.Size; i++)
    {
        ImGuiWindow* child = window->DC.ChildWindows[i];

        // Clipped children may have been marked not active
        if (child && child->Active && !child->Hidden)
        {
            _mergeDrawLists(drawList, child->DrawList);
            _mergeChildrenWindowsToDrawList(drawList, child);
        }
    }
}

RasterHelper::RasterHelper() : m_prv{ std::make_unique<RasterHelperPrivate>() }
{
    this->_setRasterPolicyChangedFn([this](const auto& policy) {
        if (policy != RasterPolicy::eNever)
        {
            this->_rasterHelperSetDirtyDrawList();
        }
    });
}

RasterHelper::~RasterHelper() = default;

void RasterHelper::invalidateRaster()
{
    this->_rasterHelperSetDirtyDrawList();
    if (m_prv)
    {
        m_prv->m_invalidatedOnDemand = true;
    }
}

void RasterHelper::_rasterHelperInit(Widget& widget)
{
    if (!m_prv)
    {
        m_prv = std::make_unique<RasterHelperPrivate>();
    }
    m_prv->m_widget = &widget;
}

void RasterHelper::_rasterHelperDestroy()
{
    this->destroyCallbacks();

    // This will destroy the draw lists when the widget is not destroyed, but
    // Widget::destroy is called.
    m_prv.reset();
}

bool RasterHelper::_rasterHelperBegin(float posX, float posY, float width, float height)
{
    if (!m_prv)
    {
        // Return true, iterate children?
        return true;
    }

    // Set dirty if the size is changed
    if (width != m_prv->m_lastWidth || height != m_prv->m_lastHeight)
    {
        m_prv->m_lastWidth = width;
        m_prv->m_lastHeight = height;
        this->_rasterHelperSetDirtyDrawList();
    }

    m_prv->m_cursor = ImGui::GetCursorScreenPos();

    // Baking logic
    bool isDrawRaster;
    ImGuiChildFlags childFlags = ImGuiChildFlags_AlwaysUseWindowPadding;
    ImGuiWindowFlags windowFlags = ImGuiWindowFlags_NoMove |
                                   ImGuiWindowFlags_NoBackground | ImGuiWindowFlags_NoScrollbar |
                                   ImGuiWindowFlags_NoScrollWithMouse | kWindowFlags_Raster;
    m_prv->m_childWindowSize = ImVec2{ width, height };
    m_prv->m_childWindowPos = ImVec2{ posX, posY };

    switch (this->getRasterPolicy())
    {
    case RasterPolicy::eOnDemand:
    {
        // Set flag indicating a separate window is needed
        m_prv->m_needSeparateWindow = true;

        // If this is the first frame after the on-demand raster has been
        // invalidated, start the countdown to capture the raster
        if (m_prv->m_invalidatedOnDemand)
        {
            m_prv->m_framesToBake = _getRasterDealy();
            m_prv->m_invalidatedOnDemand = false;
        }

        // If the countdown has reached zero, it's time to capture the raster
        if (m_prv->m_framesToBake == 0)
        {
            m_prv->m_isCaptureRaster = true;
            isDrawRaster = false;
            // Reset the countdown to the maximum value
            m_prv->m_framesToBake = UINT32_MAX;
        }
        // If the countdown is at the maximum value, it means the raster has
        // already been captured and it should be drawn
        else if (m_prv->m_framesToBake == UINT32_MAX)
        {
            m_prv->m_isCaptureRaster = false;
            isDrawRaster = true;
        }
        // If the countdown is not at zero or the maximum value, it means the
        // raster will be captured in several frames. For now, draw normally and
        // decrement the countdown
        else
        {
            m_prv->m_isCaptureRaster = false;
            isDrawRaster = false;
            m_prv->m_framesToBake--;
        }
        break;
    }

    case RasterPolicy::eAuto:
    {
        // Window flags
        m_prv->m_needSeparateWindow = true;

        // Bake when the mouse pointer leaves the window
        auto* ctx = ImGui::GetCurrentContext();
        // The window we use for baking
        ImGuiWindow* currentWindow = m_prv->m_bakeWindow ? m_prv->m_bakeWindow : ctx->CurrentWindow;
        // popup_hierarchy=true so popups opened from within the bake window
        // (e.g. ComboBox dropdowns) are treated as "inside" the frame, keeping
        // live draw active while the user interacts with the popup.
        bool hovered = ctx->HoveredWindow && currentWindow && ImGui::IsWindowChildOf(ctx->HoveredWindow, currentWindow, true, false);

        const ImGuiIO& io = ImGui::GetIO();
        constexpr float kMouseMoveEpsilon = 0.1f;
        const bool mouseMoved =
            fabsf(io.MouseDelta.x) > kMouseMoveEpsilon || fabsf(io.MouseDelta.y) > kMouseMoveEpsilon;
        const bool mouseWheel = io.MouseWheel != 0.0f || io.MouseWheelH != 0.0f;

        bool justLeaved = !hovered && m_prv->m_lastHovered;
        bool justEntered = hovered && !m_prv->m_lastHovered;
        // Keep it to know it was hovered the previous frame
        m_prv->m_lastHovered = hovered;

        // Keep drawing when the user pressed mouse in the area
        {
            if (hovered)
            {
                // when mouse pressed we consider it when it's inside the area
                for (uint8_t i = 0; i < 3; ++i)
                {
                    m_prv->m_mousePressedInsideFrame = m_prv->m_mousePressedInsideFrame | (ImGui::IsMouseClicked(i) << i);
                }
            }

            // when mouse released we consider it everywhere
            for (uint8_t i = 0; i < 3; ++i)
            {
                m_prv->m_mousePressedInsideFrame =
                    m_prv->m_mousePressedInsideFrame & ((ImGui::IsMouseDown(i) << i) | ~(1 << i));
            }
        }

        // The main cpature-show logic
        const bool hoveredNeedsLiveDraw = hovered && (justEntered || mouseMoved || mouseWheel);

        if (this->_isDirtyDrawList() || justLeaved || hoveredNeedsLiveDraw || m_prv->m_mousePressedInsideFrame ||
            m_prv->m_editingMode)
        {
            // It just became dirty, the hover state changed, the cursor is moving in the area, or mouse is pressed
            // and not released.
            // Don't capture
            m_prv->m_isCaptureRaster = false;
            // Don't draw cached
            isDrawRaster = false;

            // Start countdown
            m_prv->m_framesToBake = _getRasterDealy();
            // Undirty
            m_prv->m_drawListDirty[m_prv->m_drawListIndex] = false;
        }
        else if (m_prv->m_framesToBake == 0)
        {
            // Time to capture

            m_prv->m_isCaptureRaster = true;
            isDrawRaster = false;
            // Update counter
            m_prv->m_framesToBake = UINT32_MAX;
        }
        else if (m_prv->m_framesToBake == UINT32_MAX)
        {
            // Draw captured

            m_prv->m_isCaptureRaster = false;
            isDrawRaster = true;
        }
        else
        {
            // It will be captured in several frames. For now draw normally.

            m_prv->m_isCaptureRaster = false;
            isDrawRaster = false;
            // Update counter
            m_prv->m_framesToBake--;
        }

        break;
    }

    case RasterPolicy::eNever:
    default:
    {
        // Window flags
        m_prv->m_needSeparateWindow = false;
        m_prv->m_isCaptureRaster = false;
        isDrawRaster = false;
        break;
    }
    }

    if (m_prv->m_needSeparateWindow)
    {
        // Extend the child window to the full available area, so children are not clipped
        auto* ctx = ImGui::GetCurrentContext();
        ImGuiWindow* window = ctx->CurrentWindow;

        ImGui::SetCursorScreenPos(m_prv->m_childWindowPos);

        // WindowFlagNoBackground doesn't work
        ImGui::SetNextWindowBgAlpha(0.0f);

        ImGui::PushID(this);

        ImGui::PushStyleVar(ImGuiStyleVar_ChildRounding, 0.0f);
        ImGui::PushStyleVar(ImGuiStyleVar_ChildBorderSize, 0.0f);
        ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2{ 0.0f, 0.0f });

        ImGui::BeginChild("", m_prv->m_childWindowSize, childFlags, windowFlags);

        m_prv->m_bakeWindow = ctx->CurrentWindow;

        ImGui::PopStyleVar(3);

        // Restore the cursor
        ImGui::SetCursorScreenPos(m_prv->m_cursor);
    }

    if (isDrawRaster)
    {
        this->_drawRaster(m_prv->m_childWindowPos.x, m_prv->m_childWindowPos.y);
        return false;
    }
    // else
    {
        return true;
    }
}

void RasterHelper::_rasterHelperEnd()
{
    if (m_prv && m_prv->m_needSeparateWindow)
    {
        if (m_prv->m_isCaptureRaster)
        {
            if (_isDebugDraw())
            {
                // Color fill to visually see if this is the baked area
                ImGui::PushStyleColor(ImGuiCol_ChildBg, 0x0);
                ImGui::BeginChild("", m_prv->m_childWindowSize, false);
                ImGui::SetWindowPos(m_prv->m_childWindowPos);
                ImGui::GetWindowDrawList()->AddRectFilled(m_prv->m_childWindowPos,
                                                          { m_prv->m_childWindowPos.x + m_prv->m_childWindowSize.x,
                                                            m_prv->m_childWindowPos.y + m_prv->m_childWindowSize.y },
                                                          kDebugDrawColor);
                ImGui::GetWindowDrawList()->AddRect(m_prv->m_childWindowPos,
                                                    { m_prv->m_childWindowPos.x + m_prv->m_childWindowSize.x,
                                                      m_prv->m_childWindowPos.y + m_prv->m_childWindowSize.y },
                                                    kDebugDrawColor);
                ImGui::EndChild();
                ImGui::PopStyleColor();
            }

            // We do it before EndChild because EndChild manipulates with the
            // draw list. When we restore it, we also want the same
            // manipulations.
            this->_captureRaster(m_prv->m_childWindowPos.x, m_prv->m_childWindowPos.y);
        }

        ImGui::EndChild();
        ImGui::PopID();
    }
}

void RasterHelper::_rasterHelperSetDirtyDrawList()
{
    if (m_prv)
    {
        std::fill(m_prv->m_drawListDirty.begin(), m_prv->m_drawListDirty.end(), true);
    }
}

void RasterHelper::_rasterHelperSetDirtyLod()
{
    if (!m_prv || (this->getRasterPolicy() == RasterPolicy::eNever))
    {
        return;
    }

    // Determine current level of detail based on canvas zoom
    m_prv->m_drawListIndex = m_prv->m_widget->_getCurrentLod(m_prv->m_widget->_getCanvasZoom());

    // If the drawList is not big enough for the current level of detail, fill
    // with null pointers
    if (m_prv->m_drawList.size() <= m_prv->m_drawListIndex)
    {
        std::fill(m_prv->m_drawList.begin(), m_prv->m_drawList.end(), nullptr);
        std::fill(m_prv->m_drawListDirty.begin(), m_prv->m_drawListDirty.end(), true);
    }

    // If the drawList is not big enough or the current level of detail doesn't
    // have a drawList, set the drawList to be dirty
    if (m_prv->m_drawList.size() <= m_prv->m_drawListIndex || !m_prv->m_drawList[m_prv->m_drawListIndex])
    {
        this->_rasterHelperSetDirtyDrawList();
    }
}

void RasterHelper::_rasterHelperSuspendRasterization(bool stopRasterization)
{
    if (m_prv)
    {
        m_prv->m_editingMode = stopRasterization;
    }
}

// This function captures the raster data of the current ImGui window and its
// child windows. The origin coordinates of the captured raster data are passed
// in as the "originX" and "originY" arguments.
void RasterHelper::_captureRaster(float originX, float originY)
{
    OMNIUI_ASSERT(m_prv.get() != nullptr, "RasterHelper::_captureRaster called on invalid object");

    ImGuiContext* ctx = ImGui::GetCurrentContext();
    ImGuiWindow* imGuiWindow = ctx->CurrentWindow;

    if (m_prv->m_drawList.size() <= m_prv->m_drawListIndex)
    {
        m_prv->m_drawList.resize(m_prv->m_drawListIndex + 1);

        // This will resize and fill m_drawListDirty
        this->_isDirtyDrawList();
    }

    // Save draw list
    auto& drawList = m_prv->m_drawList[m_prv->m_drawListIndex];
    if (!drawList)
    {
        // The raster data is stored in the private member variable
        // "m_drawList".
        drawList.reset(ImGui::GetWindowDrawList()->CloneOutput());
    }
    else
    {
        // If the "m_drawList" member variable already exists, its data is
        // cleared and updated with the current raster data.
        drawList->CmdBuffer.clear();
        drawList->IdxBuffer.clear();
        drawList->VtxBuffer.clear();
        drawList->Flags = ImDrawListFlags_None;

        _mergeDrawLists(drawList.get(), ImGui::GetWindowDrawList());
    }

    _mergeChildrenWindowsToDrawList(drawList.get(), imGuiWindow);

    // Save the cursor
    m_prv->m_drawListPosition = ImVec2{ originX, originY };

    // The "m_drawListDirty" member variable is set to false to indicate that
    // the raster data is up-to-date.
    m_prv->m_drawListDirty[m_prv->m_drawListIndex] = false;
}

void RasterHelper::_drawRaster(float originX, float originY) const
{
    OMNIUI_ASSERT(m_prv.get() != nullptr, "RasterHelper::_drawRaster called on invalid object");

    if (m_prv->m_drawList.size() <= m_prv->m_drawListIndex)
    {
        m_prv->m_drawList.resize(m_prv->m_drawListIndex + 1);

        // This will resize and fill m_drawListDirty
        this->_isDirtyDrawList();
    }

    auto& drawList = m_prv->m_drawList[m_prv->m_drawListIndex];

    if (!drawList)
    {
        return;
    }

    _moveDrawList(drawList.get(), { originX - m_prv->m_drawListPosition.x, originY - m_prv->m_drawListPosition.y });
    m_prv->m_drawListPosition = ImVec2{ originX, originY };

    // Restore draw list
    ImDrawList* targetDrawList = ImGui::GetWindowDrawList();
    targetDrawList->CmdBuffer = drawList->CmdBuffer;
    targetDrawList->IdxBuffer = drawList->IdxBuffer;
    targetDrawList->VtxBuffer = drawList->VtxBuffer;
    targetDrawList->Flags = drawList->Flags;

    // Avoid ImGui asserts
    targetDrawList->_VtxWritePtr = targetDrawList->VtxBuffer.Data + targetDrawList->VtxBuffer.Size;
    targetDrawList->_IdxWritePtr = targetDrawList->IdxBuffer.Data + targetDrawList->IdxBuffer.Size;
    targetDrawList->_VtxCurrentIdx = targetDrawList->VtxBuffer.Size;
}

bool RasterHelper::_isDirtyDrawList() const
{
    OMNIUI_ASSERT(m_prv.get() != nullptr, "RasterHelper::_isDirtyDrawList called on invalid object");

    size_t drawListDirtySize = m_prv->m_drawListDirty.size();
    if (drawListDirtySize <= m_prv->m_drawListIndex)
    {
        m_prv->m_drawListDirty.resize(m_prv->m_drawListIndex + 1);
        std::fill(m_prv->m_drawListDirty.begin() + drawListDirtySize, m_prv->m_drawListDirty.end(), true);
    }
    return m_prv->m_drawListDirty[m_prv->m_drawListIndex];
}

bool RasterHelper::_isInRasterWindow() const
{
    auto* ctx = ImGui::GetCurrentContext();
    ImGuiWindow* window = ctx->CurrentWindow;
    return window && ((window->Flags & kWindowFlags_Raster) != 0);
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
