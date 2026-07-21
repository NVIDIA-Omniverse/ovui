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
#include "platform/CanvasFrameGuard.h"
#include "platform/PlatformRegistry.h"
#include "platform/IUiSettings.h"

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/Frame.h>
#include <omni/ui/Inspector.h>
#include <omni/ui/Label.h>
#include <omni/ui/Profile.h>
#include <omni/ui/Rectangle.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/StyleProperties.h>
#include <omni/ui/Widget.h>
#include <omni/ui/Workspace.h>
#include <omni/ui/ZStack.h>

#include "WidgetData.h"
#include "ImGuiKeyTranslation.h"

#include <algorithm>
#include <iterator>
#include <unordered_set>

OMNIUI_NAMESPACE_OPEN_SCOPE

namespace
{
static float g_tooltipDelay = -1.f;
}

Widget::WidgetData::~WidgetData()
{
}

std::string Widget::normalizeIdentifier(const std::string& inStr)
{
    // There is some interest in transforming incoming strings into a "normalized
    // version" for the domain-specific ui_query language (where brackets have some query-meaning)
    // ...but...there already exists prior code and tests that use brackets and spaces in the identifier
    // so as of now, the fallback will just be the incoming value, un-mutated.
    //
    return inStr;
}

Widget::Widget(WidgetData* data ) : m_data(data ? data : new WidgetData)
{
    // Recompute the style when it's changed.
    this->setParentChangedFn(std::bind(&This::cascadeStyle, this));
    this->setStyleChangedFn(std::bind(&This::cascadeStyle, this));
    this->setStyleTypeNameOverrideChangedFn(std::bind(&This::updateStyle, this));
    this->setNameChangedFn(std::bind(&This::updateStyle, this));

    this->_setVisibleChangedFn([this](auto& visible) {
        this->forceWidthDirty(SizeDirtyReason::eSizeChanged);
        this->forceHeightDirty(SizeDirtyReason::eSizeChanged);

        if (!visible)
        {
            // Invisible object can't undirty size because draw is never called.
            this->forceWidthDirty(SizeDirtyReason::eNone);
            this->forceHeightDirty(SizeDirtyReason::eNone);
        }
    });
    this->_setVisibleMinChangedFn([this](auto& min) { m_data->m_visibleMinSet = true; });
    this->_setVisibleMaxChangedFn([this](auto& max) { m_data->m_visibleMaxSet = true; });
    this->_setWidthChangedFn([this](auto& width) { this->forceWidthDirty(SizeDirtyReason::eSizeChanged); });
    this->_setHeightChangedFn([this](auto& height) { this->forceHeightDirty(SizeDirtyReason::eSizeChanged); });
    this->setTooltipChangedFn([this]() {
        if (this->hasTooltipFn())
        {
            // clear the tooltip value if needed
            this->setTooltip("");
            // clear the frame, we need to re-create it
            m_data->m_tooltipFrame = nullptr;
        }
    });
    this->_setTooltipPropertyChangedFn([this](auto& tooltip) {
        if (!tooltip.empty())
        {
            // reset the function and Frame to be null.
            this->setTooltipFn(nullptr);
            m_data->m_tooltipFrame = nullptr;
        }
    });

    this->setSelectedChangedFn([this](const auto& selected) { this->forceRasterDirty(BakeDirtyReason::eContentChanged); });

    // If identifier was assigned to on construction, and it matches name, save some memory
    // to return m_data->m_name directly (with filtering) in getIdentifier()
    //
    if (!m_identifier.empty())
    {
        m_identifier = normalizeIdentifier(m_identifier);

        // If getIdentifier is going to return the same value
        // from fallback through name property, then save some memory
        // and clear the value now.
        //
        if (m_identifier == normalizeIdentifier(m_name))
        {
            m_identifier.clear();
        }
    }

    if (g_tooltipDelay < 0.f)
    {
        if (auto* settings = PlatformRegistry::instance().settings())
        {
            g_tooltipDelay = std::max(0.f, settings->getFloat("/exts/omni.ui/tooltip_delay", 0.f));
        }
    }
}

Widget::~Widget()
{
    this->destroy();
}

void Widget::destroy()
{
    {
        // OM-94455: It seems the "raster" feature may be caching texture handles/index in a draw list
        // for later invocation/replay, which is an issue as it now may no longer exists.  Calling
        // parent->forceRasterDirty is less than ideal as destroy may have been invoked from a top-level
        // item destroying all of it's children, or multiple children being destroyed at once and
        // if a ui::Container sits in the hierarchy, it can leed to excessive traversal & invalidation.
        //
        // Ideally this could run only when (ImGui::GetCurrentContext()->CurrentWindow->Flags & kWindowFlags_Raster)
        // but as of 105.1, that still will lead to a crash.
        // Guard: if the ImGui context has already been destroyed (e.g. Python GC
        // collects widget objects after standalone shutdown), forceRasterDirty
        // would dereference a null/stale ImGui context and crash. Skip it safely.
        auto parent = this->getParent();
        if (parent && ImGui::GetCurrentContext())
        {
            parent->forceRasterDirty(BakeDirtyReason::eChildDirty);
        }
    }

    this->destroyCallbacks();
}

void Widget::_createToolTipWidgets()
{
    const auto& tooltipString = this->getTooltip();

    m_data->m_tooltipFrame = Frame::create();
    // pass the style to the frame
    m_data->m_tooltipFrame->setStyle(this->_getResolvedStyle());
    m_data->m_tooltipFrame->setStyleTypeNameOverride("Tooltip");
    m_data->m_tooltipFrame->setName(this->getName());
    OMNIKIT_WITH_CONTAINER(m_data->m_tooltipFrame)
    {
        if (this->hasTooltipFn())
        {
            this->callTooltipFn();
        }
        else if (!tooltipString.empty())
        {
            OMNIKIT_WITH_CONTAINER(ZStack::create())
            {
                auto tooltipLabel = Label::create(tooltipString);
                tooltipLabel->setStyleTypeNameOverride("Tooltip");
                tooltipLabel->setName(this->getName());
            }
        }
    }

    // make sure we compute size of child widget to fit the content.
    m_data->m_tooltipFrame->setComputedWidth(0);
    m_data->m_tooltipFrame->setComputedHeight(0);
}

void Widget::draw(float elapsedTime)
{
    auto cursor = ImGui::GetCursorScreenPos();
    m_data->m_cursorPositionXCache = cursor.x;
    m_data->m_cursorPositionYCache = cursor.y;

    const auto parent = this->getParent();
    if (parent)
    {
        m_data->m_cursorPositionOffsetXCache = m_data->m_cursorPositionXCache - parent->getScreenPositionX();
        m_data->m_cursorPositionOffsetYCache = m_data->m_cursorPositionYCache - parent->getScreenPositionY();
    }

    if (!this->isVisible())
    {
        this->setVisiblePreviousFrame(false);
        return;
    }

    // Scroll here if necessary
    if (m_data->m_scrollHereX)
    {
        m_data->m_scrollHereX = false;
        ImGui::SetScrollHereX(m_data->m_scrollHereXRatio);
    }

    if (m_data->m_scrollHereY)
    {
        m_data->m_scrollHereY = false;
        ImGui::SetScrollHereY(m_data->m_scrollHereYRatio);
    }

    this->_undirtyWidthAndHeight();

    float dpiScale = this->getDpiScale();
    bool dirtyDpi = dpiScale != m_data->m_dpiAtPreviousFrame;
    if (dirtyDpi)
    {
        m_data->m_dpiAtPreviousFrame = dpiScale;
    }

    // Adaptive visibility
    float canvasZoom = this->_getCanvasZoom();
    if (m_data->m_visibleMinSet && canvasZoom < 0.0f && dpiScale < this->getVisibleMin())
    {
        this->setVisiblePreviousFrame(false);
        return;
    }
    if (m_data->m_visibleMaxSet && canvasZoom < 0.0f && dpiScale > this->getVisibleMax())
    {
        this->setVisiblePreviousFrame(false);
        return;
    }
    // The same adaptive visibility but for canvas frame 2.0
    if (m_data->m_visibleMinSet && canvasZoom >= 0.0f && canvasZoom < this->getVisibleMin())
    {
        this->setVisiblePreviousFrame(false);
        return;
    }
    if (m_data->m_visibleMaxSet && canvasZoom >= 0.0f && canvasZoom > this->getVisibleMax())
    {
        this->setVisiblePreviousFrame(false);
        return;
    }

    if (m_data->m_marginWidthCache != 0.0f || m_data->m_marginHeightCache != 0.0f)
    {
        // TODO: For now it's the only way to apply DPI to margins. In ImGui DpiScale is only available between
        // frameBegin and frameEnd and it means we can't premultiply margins when we load them in Widget::updateStyle().
        // Apply margins
        cursor.x += m_data->m_marginWidthCache * dpiScale;
        cursor.y += m_data->m_marginHeightCache * dpiScale;
        ImGui::SetCursorScreenPos(cursor);
    }

    // We use bounding box here instead of computed content size (layout size) for use with mouse events,
    // because layout size is zero for FreeShapes, and they have a local offset for drawing and interaction.
    BoundingBox bbox = _getInteractionBBox();
    ImVec2 bboxCursor{ cursor.x + bbox.min[0], cursor.y + bbox.min[1] };
    ImVec2 computedContentSize{ bbox.max[0] - bbox.min[0], bbox.max[1] - bbox.min[1] };

    // m_data->m_computedContentWidth can be changed many times during the evaluation of
    // the layout that's why we can't call the callback from
    // setComputedContentWidth() and we have to check if the size is changed
    // here in draw().
    if (m_data->m_computedContentWidthOnDraw != m_data->m_computedContentWidth || m_data->m_computedContentHeightOnDraw != m_data->m_computedContentHeight)
    {
        m_data->m_computedContentWidthOnDraw = m_data->m_computedContentWidth;
        m_data->m_computedContentHeightOnDraw = m_data->m_computedContentHeight;

        if (this->hasComputedContentSizeChangedFn())
        {
            this->callComputedContentSizeChangedFn();
        }
    }

    ImVec2 bboxMax{ cursor.x + bbox.max[0], cursor.y + bbox.max[1] };
    if (this->isSkipDrawWhenClipped() && !dirtyDpi && !ImGui::IsRectVisible(bboxCursor, bboxMax))
    {
        this->setVisiblePreviousFrame(false);
        // It's needed to avoid the ImGui limitation of 65535 primitives in a single draw list. It's very easy to reach
        // 65535 because a character in a text is primitive.
        return;
    }

    ImGui::PushID(this);

    // Make sure the widget has size for computing mouse-related stuff.
    if (computedContentSize.x > 0.0f && computedContentSize.y > 0.0f)
    {
        // We need to use dummy to check if the item is hovered because IsMouseHoveringRect doesn't check that the item
        // is overlapped by windows.
        ImGui::SetCursorScreenPos(bboxCursor);
        ImGui::Dummy(computedContentSize);
        bool lastHovered = m_data->m_isHovered;

        ImGuiContext* ctx = ImGui::GetCurrentContext();
        OMNIUI_ASSERT(ctx);
        ImGuiWindow* window = ctx->CurrentWindow;
        OMNIUI_ASSERT(window);

        // PR7: Propagate AllowOverlap from the Dummy to interactive items
        // in _drawContent() (e.g. InvisibleButton).  The parent Stack sets
        // SetNextItemAllowOverlap() before draw(), which is consumed by the
        // Dummy above.  Store the flag so InvisibleButton::_drawContent()
        // can re-apply it to its own ImGui::InvisibleButton() call.
        m_data->m_allowItemOverlap =
            (ctx->LastItemData.ItemFlags & ImGuiItemFlags_AllowOverlap) != 0;

        constexpr ImGuiWindowFlags tooltipFlags = ImGuiWindowFlags_Tooltip | ImGuiWindowFlags_NoInputs |
                                                  ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoMove |
                                                  ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoSavedSettings |
                                                  ImGuiWindowFlags_AlwaysAutoResize | ImGuiWindowFlags_NoDocking;
        bool isTooltipWindow = (window->Flags & tooltipFlags) == tooltipFlags;
        bool blockMouseInputs = window->Flags & ImGuiWindowFlags_NoMouseInputs;

        if (!isTooltipWindow && blockMouseInputs)
        {
            // Block mouse when the window blocks mouse inputs. We need it primarily for tests to disable highlighters.
            // TODO: Block MouseClicked, MouseReleased, etc as well
            //
            // isTooltipWindow: When we are in a tooltip window, there is a
            // chance that the widget is drawn twice a frame. For example, when
            // dragging the TreeView item, we draw the item twice: in the
            // TreeView and the tooltip. In such cases, we don't need to
            // overwrite m_data->m_isPressed because it will lead to the unexpected call
            // of the callbacks.
            m_data->m_isHovered = false;
            for (uint32_t button = 0; button < kMouseButtonCount; ++button)
            {
                m_data->m_isPressed[button] = false;
            }
        }
        else
        {

            // PR7: ImGui 1.92.7 tightened IsItemHovered() checks:
            //  - AllowWhenOverlappedByItem: Our Dummy item (line 297) gets overlapped
            //    by _drawContent() items drawn on top of it each frame.
            //  - AllowWhenOverlappedByWindow: The widget's Dummy lives in a child
            //    window, but g.HoveredWindow may point to a parent/sibling window.
            //    Without this flag, IsItemHovered returns false even when the mouse
            //    is inside the Dummy rect, breaking all mouse callbacks.
            m_data->m_isHovered = ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenBlockedByActiveItem |
                                                   ImGuiHoveredFlags_AllowWhenBlockedByPopup |
                                                   ImGuiHoveredFlags_AllowWhenOverlappedByItem |
                                                   ImGuiHoveredFlags_AllowWhenOverlappedByWindow);

            m_data->m_isWindowHovered = ImGui::IsWindowHovered(ImGuiHoveredFlags_AllowWhenBlockedByPopup);

            if (this->isExplicitHover() && m_data->m_isHovered)
            {
                m_data->m_isHovered = m_data->m_isWindowHovered;
            }
            for (uint32_t button = 0; button < kMouseButtonCount; ++button)
            {
                m_data->m_isPressed[button] = ImGui::IsMouseDown(button);
            }
        }
        float dpiScaleInv = 1.0f / dpiScale;

        // TODO: this rather needs better explicit external message processing,
        //  mix of internal tracking + imgui state is explosive

        bool hasMouseCallback = this->hasMouseMovedFn() || this->hasMousePressedFn() || this->hasMouseReleasedFn() ||
                                this->hasMouseDoubleClickedFn() || this->hasMouseHoveredFn() || this->hasMouseWheelFn();
        bool hasKeyboardCallback = this->hasKeyPressedFn();

        KeyboardModifierFlags modifiers = 0;
        if (hasMouseCallback || hasKeyboardCallback)
        {
            const ImGuiIO& io = ImGui::GetIO();

            // When WantCaptureKeyboard is true, ImGui is using the keyboard input exclusively, and it's not necessary
            // to call key pressed. (e.g. InputText active, etc.).
            modifiers = (io.KeyAlt ? kKeyModAlt : 0) |
                        (io.KeyShift ? kKeyModShift : 0) |
                        (io.KeyCtrl ? kKeyModCtrl : 0) |
                        (io.KeySuper ? kKeyModSuper : 0) |
                        (io.WantCaptureKeyboard ? kModifierFlagWantCaptureKeyboard : 0);
        }

        if (hasMouseCallback && !blockMouseInputs)
        {
            auto mousePos = ImGui::GetMousePos();

            for (uint32_t button = 0; button < kMouseButtonCount; ++button)
            {
                bool isMouseClicked = ImGui::IsMouseClicked(button, false);
                if (this->hasMousePressedFn() && m_data->m_isHovered && isMouseClicked)
                {
                    if (this->isOpaqueForMouseEvents())
                    {
                        // we need an invisible button to be rendered to capture the mouse event
                        ImGui::SetCursorScreenPos(bboxCursor);
                        ImGui::InvisibleButton("", computedContentSize);
                    }
                    this->callMousePressedFn(mousePos.x * dpiScaleInv, mousePos.y * dpiScaleInv, button, modifiers);
                }

                if (m_data->m_isHovered && isMouseClicked)
                {
                    m_data->m_isClicked[button] = true;

                    if (button == 0)
                    {
                        this->setDragging(true);
                    }
                }

                if (this->hasMouseDoubleClickedFn() && m_data->m_isHovered && ImGui::IsMouseDoubleClicked(button))
                {
                    if (this->isOpaqueForMouseEvents())
                    {
                        // we need an invisible button to be rendered to capture the mouse event
                        ImGui::SetCursorScreenPos(bboxCursor);
                        ImGui::InvisibleButton("", computedContentSize);
                    }
                    this->callMouseDoubleClickedFn(mousePos.x * dpiScaleInv, mousePos.y * dpiScaleInv, button, modifiers);
                }
            }

            if (mousePos.x != m_data->m_mouseX || mousePos.y != m_data->m_mouseY)
            {
                // m_data->m_isPressed is here because the python is relatively slow, and I don't want to let multiple widgets
                // call any callback at the same time in every frame. So if the users create a hundred widgets with
                // m_data->m_mouseMovedFn, it will definitely be the bottleneck in performance. However, sometimes we need to
                // use m_data->m_mouseMovedFn for the drag and drop. That's why m_data->m_mouseMovedFn is called for the widgets the
                // user starts dragging. This limits the number of callbacks and allows us to keep good performance.
                if (this->hasMouseMovedFn() && (m_data->m_mouseX != 0.0f || m_data->m_mouseY != 0.0f) &&
                    (m_data->m_isHovered || this->isDragging()) && (m_data->m_isPressed[0] || m_data->m_isPressed[1] || m_data->m_isPressed[2]))
                {
                    if (this->isOpaqueForMouseEvents())
                    {
                        // we need an invisible button to be rendered to capture the mouse event
                        ImGui::SetCursorScreenPos(bboxCursor);
                        ImGui::InvisibleButton("", computedContentSize);
                    }
                    this->callMouseMovedFn(mousePos.x * dpiScaleInv, mousePos.y * dpiScaleInv, modifiers, m_data->m_isPressed);
                }

                // TODO: It's not good to have it in all the widgets. It should be a singleton that tracks the mouse
                // movement
                m_data->m_mouseX = mousePos.x;
                m_data->m_mouseY = mousePos.y;
            }

            // Mouse released only works if mouse was pressed and immediately released. If it was pressed and moved, we
            // need to use m_data->m_isPressed.
            if (this->isDragging() && (ImGui::IsMouseReleased(0) || !m_data->m_isPressed[0]))
            {
                if (this->hasMouseReleasedFn())
                {
                    if (this->isOpaqueForMouseEvents())
                    {
                        // we need an invisible button to be rendered to capture the mouse event
                        ImGui::SetCursorScreenPos(cursor);
                        ImGui::InvisibleButton("", computedContentSize);
                    }
                    this->callMouseReleasedFn(
                        mousePos.x * dpiScaleInv, mousePos.y * dpiScaleInv, /*button=*/0, modifiers);
                }

                this->setDragging(false);
                m_data->m_isClicked[0] = false;
            }

            for (uint32_t button = 1; button < kMouseButtonCount; ++button)
            {
                if (m_data->m_isClicked[button] && (ImGui::IsMouseReleased(button) || !m_data->m_isPressed[button]))
                {
                    if (this->hasMouseReleasedFn())
                    {
                        this->callMouseReleasedFn(mousePos.x * dpiScaleInv, mousePos.y * dpiScaleInv, button, modifiers);
                    }

                    m_data->m_isClicked[button] = false;
                }
            }

            // scroll_only_window_hovered=true (default): only fire scroll callback when
            // the widget's window is hovered (strict check via m_isHovered + IsWindowHovered).
            // scroll_only_window_hovered=false: fire scroll callback when the mouse is anywhere
            // over the widget rect, even if a child window overlaps it. We use
            // IsMouseHoveringRect which ignores window z-order (see comment at the Dummy above).
            bool scrollHovered = this->isScrollOnlyWindowHovered()
                ? (m_data->m_isHovered && ImGui::IsWindowHovered())
                : ImGui::IsMouseHoveringRect(bboxCursor, ImVec2(bboxCursor.x + computedContentSize.x, bboxCursor.y + computedContentSize.y));
            if (this->hasMouseWheelFn() && scrollHovered)
            {
                const ImGuiIO& io = ImGui::GetIO();
                if (io.MouseWheelH != 0.0f || io.MouseWheel != 0.0f)
                {
                    this->callMouseWheelFn(io.MouseWheelH, io.MouseWheel, modifiers);
                }
            }

            if (this->hasMouseHoveredFn() && lastHovered != m_data->m_isHovered)
            {
                this->callMouseHoveredFn(m_data->m_isHovered);
            }
        }

        if (hasKeyboardCallback)
        {
            // provide key events when hovering over the window.
            // ImGui 1.87+ named keys live in [ImGuiKey_NamedKey_BEGIN, _END);
            // iterating 0..256 (the legacy native range) never fires because
            // IsKeyPressed((ImGuiKey)0..255) matches nothing with
            // IMGUI_DISABLE_OBSOLETE_FUNCTIONS. Translate back to GLFW codes
            // so Python callbacks stay on the historical code space.
            if (m_data->m_isHovered)
            {
                for (int k = ImGuiKey_NamedKey_BEGIN; k < ImGuiKey_NamedKey_END; ++k)
                {
                    ImGuiKey key = static_cast<ImGuiKey>(k);
                    if (ImGui::IsKeyPressed(key, false))
                    {
                        int glfw = detail::imguiKeyToGlfwKey(key);
                        if (glfw != 0)
                            this->callKeyPressedFn(glfw, modifiers, true);
                    }
                }
                for (int k = ImGuiKey_NamedKey_BEGIN; k < ImGuiKey_NamedKey_END; ++k)
                {
                    ImGuiKey key = static_cast<ImGuiKey>(k);
                    if (ImGui::IsKeyReleased(key))
                    {
                        int glfw = detail::imguiKeyToGlfwKey(key);
                        if (glfw != 0)
                            this->callKeyPressedFn(glfw, modifiers, false);
                    }
                }
            }
        }

        // DRAG AND DROP
        // Drag
        if (this->hasDragFn())
        {
            // InvisibleButton to stick BeginDragDropSource to the specific area.
            ImGui::SetCursorScreenPos(cursor);
            ImGui::InvisibleButton("", computedContentSize);

            this->_performDrag();
        }

        // Accept Drop
        if (this->hasDropFn() && this->hasAcceptDropFn() && lastHovered != m_data->m_isHovered)
        {
            this->_performAcceptDrop();
        }

        // Drop
        if (m_data->m_dropAccepted)
        {
            // InvisibleButton to stick BeginDragDropSource to the specific area.
            ImGui::SetCursorScreenPos(cursor);
            ImGui::InvisibleButton("", computedContentSize);

            auto mousePos = ImGui::GetMousePos();
            this->_performDrop(mousePos.x * dpiScaleInv, mousePos.y * dpiScaleInv);
        }

        ImGui::SetCursorScreenPos(cursor);
    }

    // Execute custom draw code.
    {
        OMNIUI_PROFILE_VERBOSE_ZONE("[%s] _drawContent '%s'", this->getTypeName().c_str(), this->getName().c_str());

        //Save a weak-ref to this object so we can detect if it has been deleted from a callback run in _drawContent.
        //
        std::weak_ptr weakThis(weak_from_this());
        const std::string savedIdentifier(getIdentifier());
        {
            //Save a strong-ref to this object so we guarantee it cannot be destroyed during the call
            //
            std::shared_ptr strongThis(shared_from_this());
            this->_drawContent(elapsedTime);
        }

        // If we cannot re-constitute the shared_ptr from the weak_ptr, then "this" can no longer be used!
        //
        if (!weakThis.lock())
        {
            OMNIUI_LOG_ERROR("Widget[%s] was destroyed during event or draw, this is not supported", savedIdentifier.c_str());
            ImGui::PopID();
            return;
        }
    }

    bool showToolTip = m_data->m_isHovered && (this->hasTooltipFn() || !this->getTooltip().empty());
    if (showToolTip)
    {
        // accumulating the timer
        m_data->m_tooltipTimer += elapsedTime;
    }
    else if (m_data->m_tooltipTimer > 0.0f)
    {
        // reset the timer
        m_data->m_tooltipTimer = 0.0f;
    }

    // We draw the tooltip with delay if the hoveredId is set
    if (g_tooltipDelay < 60.0f && m_data->m_tooltipTimer > g_tooltipDelay)
    {
        bool forceRecreateTooltip = false;

        float tooltipOffsetX = this->getTooltipOffsetX();
        float tooltipOffsetY = this->getTooltipOffsetY();
        if (tooltipOffsetX != 0.0f || tooltipOffsetY != 0.0f)
        {
            ImGui::SetNextWindowPos(
                ImFloor(ImVec2{ cursor.x + tooltipOffsetX * dpiScale, cursor.y + tooltipOffsetY * dpiScale }));

            if (!m_data->m_tooltipShown && this->hasTooltipFn())
            {
                forceRecreateTooltip = true;
            }
        }

        // if the tooltip frame is still null, create the appropriate tooltip widgets in the frame
        if (!m_data->m_tooltipFrame || forceRecreateTooltip)
        {
            _createToolTipWidgets();
        }

        // Skip rendering if tooltip_fn created no widgets
        if (!m_data->m_tooltipFrame->_getChildren().empty())
        {
            uint32_t pushedColorCount = 0, pushedFloatCount = 0;

            // remove all padding so it is fully control by the user using styling
            ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(0, 0));
            pushedFloatCount++;

            ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, 0);
            pushedFloatCount++;

            uint32_t color;
            if (m_data->m_tooltipFrame->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &color))
            {
                // Push and Pop are very cheap in ImGui because ImVector never decreases capacity.
                ImGui::PushStyleColor(ImGuiCol_PopupBg, color);
                pushedColorCount++;
            }

            float radius;
            if (m_data->m_tooltipFrame->_resolveStyleProperty(StyleFloatProperty::eBorderRadius, &radius))
            {
                ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, radius);
                ImGui::PushStyleVar(ImGuiStyleVar_PopupRounding, radius);

                pushedFloatCount++;
                pushedFloatCount++;
            }

            float borderSize;
            if (m_data->m_tooltipFrame->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &borderSize))
            {
                ImGui::PushStyleVar(ImGuiStyleVar_PopupBorderSize, borderSize);
                pushedFloatCount++;
            }

            if (m_data->m_tooltipFrame->_resolveStyleProperty(StyleColorProperty::eBorderColor, &color))
            {
                // Push and Pop are very cheap in ImGui because ImVector never decreases capacity.
                ImGui::PushStyleColor(ImGuiCol_Border, color);
                pushedColorCount++;
            }

            // To properly display the tooltip in a canvas frame, we need to
            // temporarily uncache the mouse. This is necessary because the canvas
            // frame does not restore the position of elements that are not
            // children, and the tooltip is not a child of the canvas frame.
            // Uses g_activeCanvasFrameData (set by CanvasFrameGuard) instead of
            // the old IO.UserData aliasing hack (SRD Section 6.15).
            auto* ctx = ImGui::GetCurrentContext();
            ActiveCanvasFrameInfo* canvasInfo = g_activeCanvasFrameData;

            float cache_correction_x = 0;
            float cache_correction_y = 0;
            if (canvasInfo)
            {
                cache_correction_x = canvasInfo->cachedMousePosX - ctx->IO.MousePos.x;
                cache_correction_y = canvasInfo->cachedMousePosY - ctx->IO.MousePos.y;

                std::swap(ctx->IO.MousePos.x, canvasInfo->cachedMousePosX);
                std::swap(ctx->IO.MousePos.y, canvasInfo->cachedMousePosY);

                // due to the difference between the cachedMousePosition and userData, we need to do the correction for the
                // viewport size so that the position of the tooltip is correct.
                ctx->MouseViewport->Size.x += cache_correction_x;
                ctx->MouseViewport->Size.y += cache_correction_y;
            }

            ImGui::BeginTooltipEx(ImGuiWindowFlags_None, ImGuiTooltipFlags_OverridePrevious);
            m_data->m_tooltipFrame->draw(elapsedTime);
            ImGui::EndTooltip();

            if (canvasInfo)
            {
                std::swap(ctx->IO.MousePos.x, canvasInfo->cachedMousePosX);
                std::swap(ctx->IO.MousePos.y, canvasInfo->cachedMousePosY);

                // restore the size back after the tooltip
                ctx->MouseViewport->Size.x -= cache_correction_x;
                ctx->MouseViewport->Size.y -= cache_correction_y;
            }

            ImGui::PopStyleVar(pushedFloatCount);
            ImGui::PopStyleColor(pushedColorCount);
        }
    }

    if (showToolTip != m_data->m_tooltipShown)
    {
        m_data->m_tooltipShown = showToolTip;
    }

    uint32_t debugColor = 0x0;
    if (this->_resolveStyleProperty(StyleColorProperty::eDebugColor, &debugColor))
    {
        ImGui::GetWindowDrawList()->AddRectFilled(
            bboxCursor, { bboxCursor.x + computedContentSize.x, bboxCursor.y + computedContentSize.y }, debugColor);
    }

    ImGui::PopID();

    this->setVisiblePreviousFrame(true);
}

float Widget::getScreenPositionX() const
{
    if (!m_data->m_wasVisiblePreviousFrame)
    {
        const auto parent = this->getParent();
        if (parent)
        {
            return parent->getScreenPositionX() + m_data->m_cursorPositionOffsetXCache;
        }
    }

    return m_data->m_cursorPositionXCache;
}

float Widget::getScreenPositionY() const
{
    if (!m_data->m_wasVisiblePreviousFrame)
    {
        const auto parent = this->getParent();
        if (parent)
        {
            return parent->getScreenPositionY() + m_data->m_cursorPositionOffsetYCache;
        }
    }

    return m_data->m_cursorPositionYCache;
}

float Widget::getComputedWidth() const
{
    if (m_data->m_marginWidthCache == 0.0f)
    {
        return m_data->m_computedContentWidth;
    }

    // TODO: For now it's the only way to apply DPI to margins. In ImGui DpiScale is only available between frameBegin
    // and frameEnd and it means we can't premultiply margins when we load them in Widget::updateStyle().
    // TODO: Get rid of DPI at all
    float dpiScale = this->getDpiScale();

    return m_data->m_computedContentWidth + m_data->m_marginWidthCache * dpiScale * 2.0f;
}

float Widget::getComputedContentWidth() const
{
    return m_data->m_computedContentWidth;
}

void Widget::setComputedWidth(float width)
{
    float dpiScale = this->getDpiScale();
    // We check `dpiScale == m_data->m_dpiAtPreviousFrame` in `draw`. We check it one more time because dpiScale could change
    // during `draw`.
    if (m_data->m_dirtyWidth == SizeDirtyReason::eNone && dpiScale == m_data->m_dpiAtPreviousFrame)
    {
        return;
    }

    Inspector::bumpComputedWidthMetric();

    // TODO: For now it's the only way to apply DPI to margins. In ImGui DpiScale is only available between frameBegin
    // and frameEnd and it means we can't premultiply margins when we load them in Widget::updateStyle().
    float margin = m_data->m_marginWidthCache * dpiScale * 2.0f;

    {
        OMNIUI_PROFILE_VERBOSE_ZONE(
            "[%s] setComputedContentWidth '%s'", this->getTypeName().c_str(), this->getName().c_str());
        this->setComputedContentWidth(width - margin);
    }
}

void Widget::setComputedContentWidth(float width)
{
    m_data->m_computedContentWidth = std::max(width, 0.0f);
}

float Widget::getComputedHeight() const
{
    if (m_data->m_marginHeightCache == 0.0f)
    {
        return m_data->m_computedContentHeight;
    }

    // TODO: For now it's the only way to apply DPI to margins. In ImGui DpiScale is only available between frameBegin
    // and frameEnd and it means we can't premultiply margins when we load them in Widget::updateStyle().
    // TODO: Get rid of DPI at all
    float dpiScale = this->getDpiScale();

    return m_data->m_computedContentHeight + m_data->m_marginHeightCache * dpiScale * 2.0f;
}

float Widget::getComputedContentHeight() const
{
    return m_data->m_computedContentHeight;
}

void Widget::setComputedHeight(float height)
{
    float dpiScale = this->getDpiScale();
    // We check `dpiScale == m_data->m_dpiAtPreviousFrame` in `draw`. We check it one more time because dpiScale could change
    // during `draw`.
    if (m_data->m_dirtyHeight == SizeDirtyReason::eNone && dpiScale == m_data->m_dpiAtPreviousFrame)
    {
        return;
    }

    Inspector::bumpComputedHeightMetric();

    // TODO: For now it's the only way to apply DPI to margins. In ImGui DpiScale is only available between frameBegin
    // and frameEnd and it means we can't premultiply margins when we load them in Widget::updateStyle().
    float margin = m_data->m_marginHeightCache * dpiScale * 2.0f;

    {
        OMNIUI_PROFILE_VERBOSE_ZONE(
            "[%s] setComputedContentHeight '%s'", this->getTypeName().c_str(), this->getName().c_str());
        this->setComputedContentHeight(height - margin);
    }
}

void Widget::setComputedContentHeight(float height)
{
    m_data->m_computedContentHeight = std::max(height, 0.0f);
}

void Widget::setStyle(const StyleContainer& style)
{
    // Convert it to shared pointer.
    this->setStyle(std::make_shared<StyleContainer>(style));
}

void Widget::setStyle(StyleContainer&& style)
{
    // Move it to shared pointer.
    this->setStyle(std::make_shared<StyleContainer>(std::move(style)));
}

void Widget::updateStyle()
{
    OMNIUI_PROFILE_VERBOSE_WIDGET_FUNCTION;
    const auto& style = this->_getResolvedStyle();
    if (style)
    {
        // Save the style index for the current widget. It allows to access style properties very fast.
        m_data->m_styleStateGroupIndex = style->getStyleStateGroupIndex(this->_getStyleTypeName(), this->getName());
    }
    else
    {
        m_data->m_styleStateGroupIndex = SIZE_MAX;
    }

    // Cache margins, so there is no slow down when using them
    if (m_data->m_useMarginFromStyle)
    {
        if (!this->_resolveStyleProperty(StyleFloatProperty::eMarginWidth, &m_data->m_marginWidthCache) &&
            !this->_resolveStyleProperty(StyleFloatProperty::eMargin, &m_data->m_marginWidthCache))
        {
            m_data->m_marginWidthCache = 0.0f;
        }

        if (!this->_resolveStyleProperty(StyleFloatProperty::eMarginHeight, &m_data->m_marginHeightCache) &&
            !this->_resolveStyleProperty(StyleFloatProperty::eMargin, &m_data->m_marginHeightCache))
        {
            m_data->m_marginHeightCache = 0.0f;
        }
    }

    if (m_data->m_tooltipFrame)
    {
        m_data->m_tooltipFrame->setStyle(this->_getResolvedStyle());
    }

    this->onStyleUpdated();
    this->forceWidthDirty(SizeDirtyReason::eSizeChanged);
    this->forceHeightDirty(SizeDirtyReason::eSizeChanged);
}

void Widget::onStyleUpdated()
{
}

void Widget::cascadeStyle()
{
    this->_mergeStyleWithParent();
}

void Widget::useMarginFromStyle(bool use)
{
    m_data->m_useMarginFromStyle = use;
}

void Widget::scrollHereX(float centerRatio)
{
    m_data->m_scrollHereX = true;
    m_data->m_scrollHereXRatio = centerRatio;
}

void Widget::scrollHereY(float centerRatio)
{
    m_data->m_scrollHereY = true;
    m_data->m_scrollHereYRatio = centerRatio;
}

void Widget::scrollHere(float centerRatioX, float centerRatioY)
{
    this->scrollHereX(centerRatioX);
    this->scrollHereY(centerRatioY);
}

const std::shared_ptr<StyleContainer>& Widget::_getResolvedStyle() const
{
    if (!m_data->m_resolvedStyle)
    {
        // If there is no resolved style, get it from parent.
        const auto parent = this->getParent();
        if (parent)
        {
            return parent->_getResolvedStyle();
        }
    }

    return m_data->m_resolvedStyle;
}

const std::string& Widget::_getStyleTypeName() const
{
    const std::string& override = this->getStyleTypeNameOverride();
    return !override.empty() ? override : this->getTypeName();
}

template <typename T, typename U>
bool Widget::_resolveStyleProperty(T property, U* result) const
{
    return this->_resolveStyleProperty(property, this->_getStyleState(), result);
}

template <typename T, typename U>
bool Widget::_resolveStyleProperty(T property, StyleContainer::State state, U* result) const
{
    const auto& style = this->_getResolvedStyle();
    if (!style)
    {
        return false;
    }

    return style->resolveStyleProperty(m_data->m_styleStateGroupIndex, state, property, result);
}

StyleContainer::State Widget::_getStyleState() const
{
    if (!m_enabled)
    {
        return StyleContainer::State::eDisabled;
    }
    else if (this->_hasAcceptedDrop())
    {
        return StyleContainer::State::eDrop;
    }
    else if (this->isChecked())
    {
        return StyleContainer::State::eChecked;
    }
    else if (this->isSelected())
    {
        return StyleContainer::State::eSelected;
    }
    else if (m_data->m_isPressed[0] && m_data->m_isHovered)
    {
        return StyleContainer::State::ePressed;
    }
    else if (m_data->m_isHovered)
    {
        return StyleContainer::State::eHovered;
    }

    return StyleContainer::State::eNormal;
}

void Widget::_enableCustomChar(bool enable) const
{
    if (enable)
    {
        ImGui::GetStyle().CustomCharBegin = 0xF000;
    }
    else
    {
        ImGui::GetStyle().CustomCharBegin = 0xFFFF;
    }
}

float Widget::getDpiScale() const
{
    return Workspace::getDpiScale() * this->_getScale();
}

void Widget::forceWidthDirty(SizeDirtyReason reason)
{
    if (reason == SizeDirtyReason::eNone)
    {
        m_data->m_dirtyWidth = reason;
        return;
    }

    if (m_data->m_dirtyWidth != SizeDirtyReason::eNone)
    {
        return;
    }

    auto parent = this->getParent();
    // Guard: if the ImGui context has been destroyed (e.g. Python GC runs widget
    // destructors after standalone shutdown), propagating dirty notifications up
    // the widget tree would dereference a partially-destroyed parent and crash.
    if (parent && ImGui::GetCurrentContext())
    {
        parent->forceWidthDirty(SizeDirtyReason::eChildDirty);
    }

    m_data->m_dirtyWidth = reason;
}

void Widget::forceHeightDirty(SizeDirtyReason reason)
{
    if (reason == SizeDirtyReason::eNone)
    {
        m_data->m_dirtyHeight = reason;
        return;
    }

    if (m_data->m_dirtyHeight != SizeDirtyReason::eNone)
    {
        return;
    }

    auto parent = this->getParent();
    // Guard: same as forceWidthDirty — skip parent propagation during shutdown.
    if (parent && ImGui::GetCurrentContext())
    {
        parent->forceHeightDirty(SizeDirtyReason::eChildDirty);
    }

    m_data->m_dirtyHeight = reason;
}

void Widget::forceRasterDirty(BakeDirtyReason reason)
{
    if (reason == BakeDirtyReason::eNone)
    {
        return;
    }

    // Pass it to the parent
    Widget* parent = this->getParent();
    if (parent)
    {
        // shared_from_this may throw if the parent is no longer held by a shared_ptr
        // so we use weak_from_this and attempt to lock it to avoid that situation.
        auto weakParent = parent->weak_from_this();
        if (auto sharedParent = weakParent.lock())
        {
            if (sharedParent.get() != this->getParent())
            {
                OMNIUI_LOG_WARN("Widget::forceRasterDirty: Parent widget has changed during the call");
                return;
            }
            if (reason == BakeDirtyReason::eEditBegan || reason == BakeDirtyReason::eEditEnded)
            {
                sharedParent->forceRasterDirty(reason);
            }
            else if (reason == BakeDirtyReason::eLodDirty)
            {
                // Do nothing
            }
            else
            {
                // Child or Content is dirty
                sharedParent->forceRasterDirty(BakeDirtyReason::eChildDirty);
            }
        }
    }
}

void Widget::forceWidthDirty()
{
    this->forceWidthDirty(SizeDirtyReason::eSizeChanged);
}

void Widget::forceHeightDirty()
{
    this->forceHeightDirty(SizeDirtyReason::eSizeChanged);
}

void Widget::setVisiblePreviousFrame(bool visible, bool dirtySize)
{
    if (m_data->m_wasVisiblePreviousFrame == visible)
    {
        return;
    }

    if (dirtySize)
    {
        this->forceWidthDirty(SizeDirtyReason::eSizeChanged);
        this->forceHeightDirty(SizeDirtyReason::eSizeChanged);
    }

    m_data->m_wasVisiblePreviousFrame = visible;
}

std::string Widget::getIdentifier()
{
    if (!m_identifier.empty())
    {
        return m_identifier;
    }
    if (!m_name.empty())
    {
        return normalizeIdentifier(m_name);
    }
    return {};
}

void Widget::setIdentifier(const std::string& identifer)
{
    if (identifer != getIdentifier())
    {
        m_identifier = normalizeIdentifier(identifer);
        m_setIdentifierChangedFnCallbacks(m_identifier);
    }
}

void Widget::_mergeStyleWithParent()
{
    const auto& localStyle = this->getStyle();
    if (!localStyle)
    {
        // If there is no local style, the resolved style should be null and _getResolvedStyle() will get it from the
        // parent.
        m_data->m_resolvedStyle = nullptr;
        updateStyle();
        return;
    }

    const auto parent = this->getParent();
    if (!parent)
    {
        // If there is no parent, the resolved style should point to the local style.
        m_data->m_resolvedStyle = m_style;
        updateStyle();
        return;
    }

    const auto& parentStyle = parent->_getResolvedStyle();
    if (!parentStyle)
    {
        // If there is no style on any parent, the resolved style should point to the local style.
        m_data->m_resolvedStyle = localStyle;
        updateStyle();
        return;
    }

    // We have parent style and we have resolved style. We need to merge them and keep so if the child requests the
    // style, it will get it without conversion.
    m_data->m_resolvedStyle = std::make_shared<StyleContainer>(*parentStyle.get());
    m_data->m_resolvedStyle->merge(*localStyle.get());
    updateStyle();
}

bool Widget::_hasAcceptedDrop() const
{
    if (m_data->m_dropAccepted)
    {
        return true;
    }

    // If the widget doesn't have drop stuff, we ask the parent to be able to customize drop area with many custom
    // widgets.
    if (!this->hasAcceptDropFn() || !this->hasDropFn())
    {
        // TODO: We need to have some flag that shows that no parent has any DnD code to avoid access the parent because
        // lock is slow.
        const auto parent = this->getParent();
        if (parent)
        {
            return parent->_hasAcceptedDrop();
        }
    }

    return false;
}

void Widget::_undirtyWidthAndHeight(bool force)
{
    // If the size is in pixels, it will not be changed even if the size of parent is changed.
    if (m_data->m_dirtyWidth != SizeDirtyReason::eNone)
    {
        m_data->m_dirtyWidth = SizeDirtyReason::eNone;
    }
    if (m_data->m_dirtyHeight != SizeDirtyReason::eNone)
    {
        m_data->m_dirtyHeight = SizeDirtyReason::eNone;
    }
}

bool Widget::_isParentCanvasFrame() const
{
    // Get the parent of the widget
    const Widget* parent = this->getParent();
    // If the widget has a parent
    if (parent)
    {
        // Recursively check the parent's parent
        return parent->_isParentCanvasFrame();
    }
    // If the widget doesn't have a parent, return false
    return false;
}

void Widget::_fillVisibleThreshold(void* thresholds) const
{
    // The void pointer is casted to a std::unordered_set<float>* type.
    std::unordered_set<float>* set = reinterpret_cast<std::unordered_set<float>*>(thresholds);

    // The visible minimum and maximum values are inserted into the unordered set.
    set->insert(this->getVisibleMin());
    set->insert(this->getVisibleMax());
}

size_t Widget::_getCurrentLod(float zoom) const
{
    if (zoom < 0.0f)
    {
        return 0;
    }

    // Create an unordered set to store the visible thresholds
    std::unordered_set<float> thresholds;

    // Fill the set with visible thresholds, it collects all the
    // visibleMin and visibleMax properties from all the children.
    this->_fillVisibleThreshold(&thresholds);

    // Reserve space in the vector for the thresholds
    std::vector<float> thresholdsSorted;
    thresholdsSorted.reserve(thresholds.size());

    // Copy the thresholds from the set to the vector and sort them in
    // ascending order. It shouldn't be expensive because normally we
    // have only 3 values.
    std::copy(thresholds.begin(), thresholds.end(), std::back_inserter(thresholdsSorted));
    std::sort(thresholdsSorted.begin(), thresholdsSorted.end());

    // Find the position of the threshold above the current zoom level.
    // It's our LOD number.
    auto it = std::upper_bound(thresholdsSorted.begin(), thresholdsSorted.end(), zoom);
    return std::distance(thresholdsSorted.begin(), it) - 1;
}

Widget::BoundingBox Widget::_getInteractionBBox() const
{
    BoundingBox bbox;
    bbox.min[0] = 0.0f;
    bbox.min[1] = 0.0f;
    bbox.max[0] = m_data->m_computedContentWidth;
    bbox.max[1] = m_data->m_computedContentHeight;
    return bbox;
}

void Widget::_performDrag()
{
    // TODO: Use ImGuiDragDropFlags_SourceNoPreviewTooltip when m_data->m_dragFrame returns nothing.
    if (ImGui::BeginDragDropSource(ImGuiDragDropFlags_None))
    {
        if (!m_data->m_dragActive)
        {
            // This frame will have the tooltip widget that follows the mouse to show what user drags.
            if (!m_data->m_dragFrame)
            {
                OMNIKIT_WITH_CONTAINER(nullptr)
                {
                    m_data->m_dragFrame = Frame::create();
                }
            }

            OMNIKIT_WITH_CONTAINER(m_data->m_dragFrame)
            {
                m_data->m_dragAndDropBuffer = this->callDragFn();
            }

            m_data->m_dragFrame->setComputedWidth(0.0f);
            m_data->m_dragFrame->setComputedHeight(0.0f);

            m_data->m_dragActive = true;
        }

        if (!m_data->m_dragAndDropBuffer.empty())
        {
            // Data for drag. It's called every frame during drag.
            ImGui::SetDragDropPayload(
                Widget::getDragDropPayloadId(), m_data->m_dragAndDropBuffer.data(), m_data->m_dragAndDropBuffer.size() + 1);

            // Draw the widget.
            m_data->m_dragFrame->draw(0.0f);
        }

        ImGui::EndDragDropSource();
    }
    else if (m_data->m_dragActive)
    {
        m_data->m_dragAndDropBuffer.clear();
        m_data->m_dragActive = false;
    }
}

void Widget::_performAcceptDrop()
{
    if (m_data->m_isHovered)
    {
        const ImGuiPayload* payload = ImGui::GetDragDropPayload();
        if (payload && payload->IsDataType(Widget::getDragDropPayloadId()))
        {
            const char* dragAndDropPayloadBuffer = reinterpret_cast<const char*>(payload->Data);
            m_data->m_dropAccepted = this->callAcceptDropFn(dragAndDropPayloadBuffer);
        }
    }
    else if (m_data->m_dropAccepted)
    {
        m_data->m_dropAccepted = false;
    }
}

void Widget::_performDrop(float x, float y)
{
    ImGui::PushStyleColor(ImGuiCol_DragDropTarget, 0x0);
    if (ImGui::BeginDragDropTarget())
    {
        if (const ImGuiPayload* payload = ImGui::AcceptDragDropPayload(nullptr))
        {
            const char* dragAndDropPayloadBuffer = reinterpret_cast<const char*>(payload->Data);
            this->callDropFn(MouseDropEvent{ x, y, dragAndDropPayloadBuffer });
            m_data->m_dropAccepted = false;
        }
        ImGui::EndDragDropTarget();
    }
    ImGui::PopStyleColor();
}

bool Widget::isWindowHovered() const
{
    return m_data->m_isWindowHovered;
}

bool Widget::isHovered() const
{
    return m_data->m_isHovered;
}

bool Widget::setHovered(bool hovered)
{
    m_data->m_isHovered = hovered;
    return hovered;
}

bool Widget::isPressed(uint32_t button) const
{
    return m_data->m_isPressed[button % kMouseButtonCount];
}

bool Widget::isClicked(uint32_t button) const
{
    return m_data->m_isClicked[button % kMouseButtonCount];
}

bool Widget::useMarginFromStyle() const
{
    return m_data->m_useMarginFromStyle;
}

Widget::SizeDirtyReason Widget::isWidthDirty() const
{
    return m_data->m_dirtyWidth;
}

Widget::SizeDirtyReason Widget::isHeightDirty() const
{
    return m_data->m_dirtyHeight;
}


template OMNIUI_API bool Widget::_resolveStyleProperty<StyleFloatProperty, float>(StyleFloatProperty property,
                                                                                  float* result) const;

template OMNIUI_API bool Widget::_resolveStyleProperty<StyleEnumProperty, uint32_t>(StyleEnumProperty property,
                                                                                    uint32_t* result) const;

template OMNIUI_API bool Widget::_resolveStyleProperty<StyleColorProperty, uint32_t>(StyleColorProperty property,
                                                                                     uint32_t* result) const;

template OMNIUI_API bool Widget::_resolveStyleProperty<StyleStringProperty, const char*>(StyleStringProperty property,
                                                                                         const char** result) const;

template OMNIUI_API bool Widget::_resolveStyleProperty<StyleFloatProperty, float>(StyleFloatProperty property,
                                                                                  StyleContainer::State state,
                                                                                  float* result) const;

template OMNIUI_API bool Widget::_resolveStyleProperty<StyleEnumProperty, uint32_t>(StyleEnumProperty property,
                                                                                    StyleContainer::State state,
                                                                                    uint32_t* result) const;

template OMNIUI_API bool Widget::_resolveStyleProperty<StyleColorProperty, uint32_t>(StyleColorProperty property,
                                                                                     StyleContainer::State state,
                                                                                     uint32_t* result) const;

template OMNIUI_API bool Widget::_resolveStyleProperty<StyleStringProperty, const char*>(StyleStringProperty property,
                                                                                         StyleContainer::State state,
                                                                                         const char** result) const;

OMNIUI_NAMESPACE_CLOSE_SCOPE
