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
#include <omni/ui/Profile.h>
#include <omni/ui/Stack.h>
#include <omni/ui/StyleContainer.h>

#include "StackData.h"

#include <algorithm>

OMNIUI_NAMESPACE_OPEN_SCOPE

static inline bool isHorizontal(Stack::Direction direction)
{
    return direction == Stack::Direction::eLeftToRight || direction == Stack::Direction::eRightToLeft;
}

static inline bool isVertical(Stack::Direction direction)
{
    return direction == Stack::Direction::eTopToBottom || direction == Stack::Direction::eBottomToTop;
}

static inline bool isReversed(Stack::Direction direction)
{
    return direction == Stack::Direction::eRightToLeft || direction == Stack::Direction::eBottomToTop ||
           direction == Stack::Direction::eFrontToBack;
}

Stack::StackData::~StackData()
{
}

Stack::Stack(Direction direction, StackData* stackData)
    : Container(stackData ? stackData : new StackData)
{
    this->setDirection(direction);

    this->setSelectedChangedFn([this](const auto& selected) {
        for (auto& child : _getChildren())
        {
            if (OMNIUI_LIKELY(child))
            {
                child->setSelected(selected);
            }
        }
    });
    this->setCheckedChangedFn([this](const auto& checked) {
        for (auto& child : _getChildren())
        {
            if (OMNIUI_LIKELY(child))
            {
                child->setChecked(checked);
            }
        }
    });
    this->setEnabledChangedFn([this](const auto& enabled) {
        for (auto& child : _getChildren())
        {
            if (OMNIUI_LIKELY(child))
            {
                child->setEnabled(enabled);
            }
        }
    });
    this->_setScaleChangedFn([this](const auto& scale) {
        for (auto& child : _getChildren())
        {
            if (OMNIUI_LIKELY(child))
            {
                child->setScale(scale);
            }
        }
    });
    this->_setCanvasZoomChangedFn([this](const auto& zoom) {
        for (auto& child : _getChildren())
        {
            if (OMNIUI_LIKELY(child))
            {
                child->setCanvasZoom(zoom);
            }
        }
    });
}

Stack::~Stack()
{
    OMNIUI_ASSERT(_getData<StackData>().m_drawCallData == nullptr);
    this->destroy();
}

void Stack::destroy()
{
    StackData& data = _getData<StackData>();
    if (OMNIUI_UNLIKELY(data.destroy()))
    {
        return;
    }

    this->clear();
    Widget::destroy();
}

void Stack::addChild(std::shared_ptr<Widget> widget)
{
    if (OMNIUI_UNLIKELY(!widget))
    {
        OMNIUI_LOG_ERROR("Stack::addChild attempting to add an invalid widget");
        return;
    }
    StackData& data = _getData<StackData>();
    if (OMNIUI_UNLIKELY(data.addChild(widget)))
    {
        return;
    }

    data.m_children.push_back(widget);
    widget->useMarginFromStyle(useMarginFromStyle());

    widget->setSelected(this->isSelected());
    widget->setChecked(this->isChecked());
    widget->setEnabled(this->isEnabled());
    widget->setScale(this->_getScale());
    widget->setCanvasZoom(this->_getCanvasZoom());

    this->forceWidthDirty(SizeDirtyReason::eChildDirty);
    this->forceHeightDirty(SizeDirtyReason::eChildDirty);
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void Stack::clear()
{
    StackData& data = _getData<StackData>();
    if (OMNIUI_UNLIKELY(data.clear()))
    {
        return;
    }

    // Move m_children into a local object so any subsequent insertion or removal won't corrupt the iterators.
    std::vector<std::shared_ptr<Widget>> children(std::move(data.m_children));

    for (auto& child : children)
    {
        if (child)
        {
            child->destroy();
            child->setParent(nullptr);
        }
    }

    // Issue a warning if somehow children were added during the clear.
    if (OMNIUI_UNLIKELY(!data.m_children.empty()))
    {
        OMNIUI_LOG_ERROR("Children were added during clear, this is not supported");
    }
}

void Stack::setComputedContentWidth(float width)
{
    float evaluatedWidth;
    if (isHorizontal(this->getDirection()))
    {
        evaluatedWidth = _evaluateConsecutiveLayout(width, true);
    }
    else
    {
        evaluatedWidth = _evaluateSimultaneousLayout(width, true);
    }

    Widget::setComputedContentWidth(evaluatedWidth);
}

void Stack::setComputedContentHeight(float height)
{
    float evaluatedHeight;
    if (isVertical(this->getDirection()))
    {
        evaluatedHeight = _evaluateConsecutiveLayout(height, false);
    }
    else
    {
        evaluatedHeight = _evaluateSimultaneousLayout(height, false);
    }

    Widget::setComputedContentHeight(evaluatedHeight);
}

void Stack::cascadeStyle()
{
    Widget::cascadeStyle();

    for (const auto& child : _getChildren())
    {
        if (OMNIUI_LIKELY(child))
        {
            child->cascadeStyle();
        }
    }
}

void Stack::forceRasterDirty(BakeDirtyReason reason)
{
    if (reason == BakeDirtyReason::eLodDirty)
    {
        for (const auto& child : _getChildren())
        {
            if (OMNIUI_LIKELY(child))
            {
                child->forceRasterDirty(reason);
            }
        }
    }

    Widget::forceRasterDirty(reason);
}

void Stack::setVisiblePreviousFrame(bool wasVisible, bool dirtySize)
{
    if (!wasVisible)
    {
        for (const auto& child : _getChildren())
        {
            if (OMNIUI_LIKELY(child))
            {
                child->setVisiblePreviousFrame(wasVisible, false);
            }
        }
    }

    Widget::setVisiblePreviousFrame(wasVisible, dirtySize);
}

void Stack::_drawContent(float elapsedTime)
{
    Container::ContainerData::DrawCallData drawCache(std::static_pointer_cast<Container>(shared_from_this()), _getData<StackData>());

    // TODO: We will get rid of dpiScale soon
    float dpiScale = this->getDpiScale();

    // Compute the scale of one unit for column length.
    float spacing = this->getSpacing() * dpiScale;

    auto direction = this->getDirection();
    bool horizontal = isHorizontal(direction);
    bool vertical = isVertical(direction);
    bool sendMouseToBack = this->isSendMouseEventsToBack();

    auto previousCursor = ImGui::GetCursorScreenPos();
    auto currentCursor = previousCursor;

    uint32_t debugColor = 0x0;
    if (this->_resolveStyleProperty(StyleColorProperty::eDebugColor, &debugColor))
    {
        // we adjust the color of the frame so this can play nicely with the drawing that happen at the widget level
        debugColor = std::min(static_cast<uint32_t>(debugColor * 2), 0xFFFFFFFF);
    }

    auto contentClipping = this->isContentClipping();
    if (contentClipping)
    {
        ImGui::PushID(this);

        // WindowFlagNoBackground doesn't work here because the docking code sets it as well. The only way to have
        // transparent background is to set alpha.
        ImGui::SetNextWindowBgAlpha(0.0f);

        // Create a window with the specified size.
        // TODO: at this point we know if this area is visible. Do we need to early out?
        ImGui::BeginChild("", { this->getComputedContentWidth(), this->getComputedContentHeight() }, false,
                          ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse);
    }

    bool reversed = isReversed(direction);

    const auto& children = _getChildren();
    for (size_t i = 0, n = children.size(); i < n; ++i)
    {
        const size_t currentSize = children.size();
        if (currentSize != n)
        {
          OMNIUI_LOG_ERROR("Unexpected state. Number of children increased from %zu to %zu", n, currentSize);
          if (i >= currentSize)
          {
            break;
          }
          n = currentSize;
        }

        std::shared_ptr<Widget> child(reversed ? children[n-(i+1)] : children[i]);
        if (!child)
        {
            OMNIUI_LOG_ERROR("Unexpected state. No child in m_children[%zu]", i);
            continue;
        }

        if (!child->isVisible())
        {
            // Skip non-visible children
            continue;
        }

        ImGui::SetCursorScreenPos(currentCursor);

        // As an optimization, when passing mouse events to overlapping widgets ImGui ignores the overlap and
        // gives the event to the first widget drawn. Normally this is fine but for a Z-based stack it always
        // results in the event going to the widget at the bottom of the stack, which is rarely what is desired.
        //
        // We can fix this by letting ImGui know that the stack's children may overlap.
        //
        if (!vertical && !horizontal && !sendMouseToBack)
        {
            ImGui::SetNextItemAllowOverlap();
        }

        child->draw(elapsedTime);

        float childWidth = child->getComputedWidth();
        float childHeight = child->getComputedHeight();

        if (debugColor)
        {
            float childWidth = child->getComputedWidth();
            float childHeight = child->getComputedHeight();
            ImGui::GetWindowDrawList()->AddRect(
                currentCursor, { currentCursor.x + childWidth + spacing, currentCursor.y + childHeight + spacing },
                debugColor, 0, 0, 1);
        }

        // Move the cursor according to the layout
        if (horizontal)
        {
            float childWidth = child->getComputedWidth();
            currentCursor.x += childWidth + spacing;
        }
        else if (vertical)
        {
            float childHeight = child->getComputedHeight();
            currentCursor.y += childHeight + spacing;
        }
    }

    if (contentClipping)
    {
        ImGui::EndChild();
        ImGui::PopID();
    }

    ImGui::SetCursorScreenPos(previousCursor);
}

std::vector<std::shared_ptr<Widget>> Stack::_getChildren() const
{
    return _getData<StackData>().m_children;
}

std::vector<std::shared_ptr<Widget>>& Stack::_getMutableChildren()
{
    return _getData<StackData>().m_children;
}

void Stack::_fillVisibleThreshold(void* thresholds) const
{
    Widget::_fillVisibleThreshold(thresholds);

    for (const auto& child : _getChildren())
    {
        if (OMNIUI_LIKELY(child))
        {
            child->_fillVisibleThreshold(thresholds);
        }
    }
}

float Stack::_evaluateConsecutiveLayout(float length, bool isWidthEvaluation)
{
    OMNIUI_PROFILE_VERBOSE_WIDGET_FUNCTION;

    // Computing length. The main idea of this layout is to compute the size of the child widgets and adjust the size
    // after computing. So it's 2 passes layout. We need to adjust the size because the widgets are free to readjust
    // their geometry to fit the content when it's necessary.

    // TODO: We will get rid of dpiScale soon
    float dpiScale = this->getDpiScale();

    // Skip invisible children.
    auto& children = _getData<StackData>().m_children;
    size_t visibleChildrenNumber = std::count_if(
        children.begin(), children.end(), [](const std::shared_ptr<Widget>& w) { return w->isVisible(); });

    // Compute the scale of one unit for column length.
    float totalSpacing = visibleChildrenNumber == 0 ? 0.0f : (visibleChildrenNumber - 1) * this->getSpacing() * dpiScale;
    float availableLength = length - totalSpacing;
    float lengthLeftForFractions = availableLength;
    float totalFractionsFromChildren = 0.0f;
    float totalLengthFromChildren = 0.0f;

    // Working with Pixel and Percent widgets. They don't depend on the length of others so they can be computed right
    // away in one pass.
    for (auto& child : children)
    {
        if (!child || !child->isVisible())
        {
            // Skip invisible children.
            continue;
        }

        float computedLength;
        const auto& currentLength = isWidthEvaluation ? child->getWidth() : child->getHeight();
        if (currentLength.unit == UnitType::ePixel)
        {
            computedLength = currentLength.value * dpiScale;
        }
        else if (currentLength.unit == UnitType::ePercent)
        {
            computedLength = currentLength.value * 1e-2f * availableLength;
        }
        else // if (currentLength.unit == UnitType::eFraction)
        {
            totalFractionsFromChildren += currentLength.value;
            // If it's Fraction, we will set it on the second pass.
            continue;
        }

        this->_forceChildDirty(child, isWidthEvaluation);

        if (isWidthEvaluation)
        {
            child->setComputedWidth(computedLength);
            computedLength = child->getComputedWidth();
        }
        else
        {
            child->setComputedHeight(computedLength);
            computedLength = child->getComputedHeight();
        }

        lengthLeftForFractions -= computedLength;
        totalLengthFromChildren += computedLength;
    }

    // Working with Fraction widgets. They depend on the size of each others and should be computed in (TODO) two passes
    for (auto& child : children)
    {
        if (!child || !child->isVisible())
        {
            // Skip invisible children.
            continue;
        }

        const auto& currentLength = isWidthEvaluation ? child->getWidth() : child->getHeight();

        if (currentLength.unit == UnitType::ePixel)
        {
            continue;
        }
        else if (currentLength.unit == UnitType::ePercent)
        {
            continue;
        }
        // else if (currentLength.unit == UnitType::eFraction)

        // Set the lengths of the Fraction units.
        float fractionScale = lengthLeftForFractions / totalFractionsFromChildren;
        float computedLength = totalFractionsFromChildren == 0.0f ? 0.0f : currentLength.value * fractionScale;

        this->_forceChildDirty(child, isWidthEvaluation);

        float computedLengthFromChild;
        if (isWidthEvaluation)
        {
            child->setComputedWidth(computedLength);
            computedLengthFromChild = child->getComputedWidth();
        }
        else
        {
            child->setComputedHeight(computedLength);
            computedLengthFromChild = child->getComputedHeight();
        }

        // TODO: What if the last one changes the size? Two passes, like in _evaluateSimultaneousLayout would be better.
        lengthLeftForFractions -= computedLengthFromChild;
        totalFractionsFromChildren -= currentLength.value;

        totalLengthFromChildren += computedLengthFromChild;
    }

    // final length:
    float totalLength = totalLengthFromChildren + totalSpacing;
    return totalLength;
}

float Stack::_evaluateSimultaneousLayout(float length, bool isWidthEvaluation)
{
    OMNIUI_PROFILE_VERBOSE_WIDGET_FUNCTION;

    float maxLength = length;

    // If one of the widgets expands the boundaries of the stack, we need to readjust other children that depend on
    // the parent size. So it's a two-step algorithm. In the first step, we set the geometry, and if one of the
    // children expands provided size, we do the second iteration and provide other children the new size. This
    // approach requires two calls of setComputedSize. The alternative solution to this would be introducing a way
    // to get the minimal size from the widget, which increases the complexity of the code.
    for (int32_t i = 0; i < 2; ++i)
    {
        for (auto& child : _getData<StackData>().m_children)
        {
            if (!child || !child->isVisible())
            {
                // Skip invisible children.
                continue;
            }

            float computedLength;
            const auto& currentLength = isWidthEvaluation ? child->getWidth() : child->getHeight();
            if (currentLength.unit == UnitType::ePixel)
            {
                float dpiScale = this->getDpiScale();
                computedLength = currentLength.value * dpiScale;
            }
            else if (currentLength.unit == UnitType::ePercent)
            {
                computedLength = currentLength.value * 1e-2f * maxLength;
            }
            else // if (currentLength.unit == UnitType::eFraction)
            {
                computedLength = maxLength;
            }

            this->_forceChildDirty(child, isWidthEvaluation);

            if (isWidthEvaluation)
            {
                child->setComputedWidth(computedLength);
                computedLength = child->getComputedWidth();
            }
            else
            {
                child->setComputedHeight(computedLength);
                computedLength = child->getComputedHeight();
            }

            maxLength = std::max(maxLength, computedLength);
        }

        if (_getChildren().size() == 1 || maxLength == length)
        {
            // The widget was not expanded by one of the children. We don't need to do the second pass and readjust
            // other children.
            break;
        }
    }

    return maxLength;
}

void Stack::_forceChildDirty(std::shared_ptr<Widget>& child, bool width) const
{
    SizeDirtyReason dirtyReason = width ? isWidthDirty() : isHeightDirty();
    const Length& childSize = width ? child->getWidth() : child->getHeight();

    bool dirty = false;

    if (dirtyReason == SizeDirtyReason::eSizeChanged || dirtyReason == SizeDirtyReason::eParentDirty)
    {
        if (childSize.unit == UnitType::ePercent || childSize.unit == UnitType::eFraction)
        {
            dirty = true;
        }
    }
    else if (dirtyReason == SizeDirtyReason::eChildDirty)
    {
        if (childSize.unit == UnitType::eFraction)
        {
            dirty = true;
        }
    }
    else
    {
        return;
    }

    if (dirty)
    {
        if (width)
        {
            child->forceWidthDirty(SizeDirtyReason::eParentDirty);
        }
        else
        {
            child->forceHeightDirty(SizeDirtyReason::eParentDirty);
        }
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
