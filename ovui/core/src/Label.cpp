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
#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/Label.h>
#include <omni/ui/StyleContainer.h>

#include "WidgetData.h"

OMNIUI_NAMESPACE_OPEN_SCOPE


struct Label::LabelData : public Widget::WidgetData
{
    ~LabelData() override = default;

    // Flag that the text size is computed. We need it because we don't want to compute the size each call of draw().
    bool m_textMinimalSizeComputed = false;
    float m_textMinimalWidth;
    float m_textMinimalHeight;

    // We need it for multiline eliding.
    float m_lastAvailableHeight = 0.0f;

    // The pointer to the font that is used by this label.
    void* m_font = nullptr;
};


/**
 * @brief Returns the offset to align the content inside the container.
 */
float _alignmentHOffset(const Alignment& alignment, float contentWidth, float containerWidth)
{
    if (alignment & Alignment::eRight)
    {
        return containerWidth - contentWidth;
    }
    else if (alignment & Alignment::eHCenter)
    {
        return 0.5f * (containerWidth - contentWidth);
    }
    // else

    return 0.0f;
}

/**
 * @brief Returns the offset to align the content inside the container.
 */
float _alignmentVOffset(const Alignment& alignment, float contentHeight, float containerHeight)
{
    if (alignment & Alignment::eBottom)
    {
        return containerHeight - contentHeight;
    }
    else if (alignment & Alignment::eVCenter)
    {
        return 0.5f * (containerHeight - contentHeight);
    }
    // else

    return 0.0f;
}

/**
 * @brief Get the last character in the string that fits to the given width. It keeps the left part of the string.
 */
static const char* _getLeftElidedPosition(const char* beginText, const char* endText, float width)
{
    float textWidth = 0.0f;
    for (const char* i = beginText; i < endText; ++i)
    {
        auto textSize = ImGui::CalcTextSize(i, i + 1);
        textWidth += textSize.x;
        if (textWidth > width)
        {
            return i;
        }
    }

    return endText;
}

/**
 * @brief Get the first character in the string that fits to the given width. It keeps the right part of the string.
 */
static const char* _getRightElidedPosition(const char* beginText, const char* endText, float width)
{
    float textWidth = 0.0f;
    for (const char* i = endText; i > beginText; --i)
    {
        auto textSize = ImGui::CalcTextSize(i - 1, i);
        textWidth += textSize.x;
        if (textWidth > width)
        {
            return i;
        }
    }

    return beginText;
}

static void _drawElidedText(ImGuiContext* ctx,
                            const ImVec2& pos,
                            const char* textBegin,
                            const char* textEnd,
                            const char* dots,
                            float width,
                            ImU32 color,
                            const Alignment& alignment)
{
    auto window = ctx->CurrentWindow;
    OMNIUI_ASSERT(window);
    auto drawList = window->DrawList;
    OMNIUI_ASSERT(drawList);
    auto font = ctx->Font;
    OMNIUI_ASSERT(font);

    auto textSize = ImGui::CalcTextSize(textBegin, textEnd);

    if (textSize.x <= width + 1e-6f)
    {
        float offset = _alignmentHOffset(alignment, textSize.x, width);

        // It fits. Draw a normal line.
        ImVec2 textPosition{ offset + pos.x, pos.y };
        drawList->AddText(font, ctx->FontSize, textPosition, color, textBegin, textEnd);
        return;
    }

    auto dotsSize = ImGui::CalcTextSize(dots);

    const char* textLeftEnd = _getLeftElidedPosition(textBegin, textEnd, width * 0.5f - dotsSize.x * 0.5f);
    auto textLeftSize = ImGui::CalcTextSize(textBegin, textLeftEnd);

    const char* textRightBegin = _getRightElidedPosition(textLeftEnd, textEnd, width * 0.5f - dotsSize.x * 0.5f);
    auto textRightSize = ImGui::CalcTextSize(textRightBegin, textEnd);

    float offset = _alignmentHOffset(alignment, textLeftSize.x + dotsSize.x + textRightSize.x, width);

    ImVec2 textLeftPosition{ offset + pos.x, pos.y };
    drawList->AddText(font, ctx->FontSize, textLeftPosition, color, textBegin, textLeftEnd);

    ImVec2 textDotsPosition{ offset + pos.x + textLeftSize.x, pos.y };
    drawList->AddText(font, ctx->FontSize, textDotsPosition, color, dots);

    ImVec2 textRightPosition{ offset + pos.x + textLeftSize.x + dotsSize.x, pos.y };
    drawList->AddText(font, ctx->FontSize, textRightPosition, color, textRightBegin, textEnd);
}

Label::Label(const std::string& text)
    : Widget(new LabelData)
{
    this->setText(text);
    this->setTextChangedFn([this](const auto&) {
        _getData<LabelData>().m_textMinimalSizeComputed = false;
        this->forceWidthDirty(SizeDirtyReason::eSizeChanged);
        this->forceHeightDirty(SizeDirtyReason::eSizeChanged);
        this->forceRasterDirty(Widget::BakeDirtyReason::eContentChanged);
    });
    this->_setScaleChangedFn([this](const auto&) {
        _getData<LabelData>().m_textMinimalSizeComputed = false; }
    );
}

Label::~Label() = default;

void Label::setComputedContentWidth(float width)
{
    const auto& data = _getData<LabelData>();
    this->_computeTextSize(width);
    Widget::setComputedContentWidth(std::max(width, data.m_textMinimalWidth));
}

void Label::setComputedContentHeight(float height)
{
    auto& data = _getData<LabelData>();
    data.m_lastAvailableHeight = height;
    this->_computeTextSize(this->getComputedContentWidth());
    Widget::setComputedContentHeight(std::max(height, data.m_textMinimalHeight));
}

void Label::onStyleUpdated()
{
    _getData<LabelData>().m_textMinimalSizeComputed = false;
}

float Label::exactContentWidth()
{
    this->_computeTextSize(this->getComputedContentWidth());
    return _getData<LabelData>().m_textMinimalWidth;
}

float Label::exactContentHeight()
{
    this->_computeTextSize(this->getComputedContentWidth());
    return _getData<LabelData>().m_textMinimalHeight;
}

void Label::_drawContent(float elapsedTime)
{
    uint32_t color;
    bool colorResolved = this->_resolveStyleProperty(StyleColorProperty::eColor, &color);

    if (colorResolved)
    {
        // Push and Pop are very cheap in ImGui because ImVector never decreases capacity.
        ImGui::PushStyleColor(ImGuiCol_Text, color);
    }

    // The alignment
    float width = this->getComputedContentWidth();
    float height = this->getComputedContentHeight();

    uint32_t align = static_cast<uint32_t>(this->getAlignment());
    this->_resolveStyleProperty(StyleEnumProperty::eAlignment, &align);
    Alignment alignment = static_cast<Alignment>(align);

    auto& data = _getData<LabelData>();
    auto cursor = ImGui::GetCursorScreenPos();
    cursor.x += _alignmentHOffset(alignment, data.m_textMinimalWidth, width);
    cursor.y += _alignmentVOffset(alignment, data.m_textMinimalHeight, height);

    this->_pushFont(*this, this->_isParentCanvasFrame());

    // alignWrap forces text with newlines to use wrapwrapping
    // so it can align each line individually
    bool alignWrap = (this->getText().find("\n") != std::string::npos);
    if (this->isWordWrap() || alignWrap)
    {
        bool isElided = this->isElidedText();

        if (alignment & Alignment::eHCenter || alignment & Alignment::eRight || isElided || alignWrap)
        {
            // Low level text output with the center alignment.
            // ImGui doesn't support text wrapping with the center alignment. This is the code that follows
            // `ImFont::RenderText` closely but draws center-aligned text.
            auto ctx = ImGui::GetCurrentContext();
            OMNIUI_ASSERT(ctx);
            auto window = ctx->CurrentWindow;
            OMNIUI_ASSERT(window);
            auto drawList = window->DrawList;
            OMNIUI_ASSERT(drawList);
            auto font = ctx->Font;
            OMNIUI_ASSERT(font);
            auto textColor = ImGui::GetColorU32(ImGuiCol_Text);

            const char* textBegin = this->getText().c_str();
            const char* textEnd = textBegin + this->getText().length();

            float availableHeight = std::max(data.m_lastAvailableHeight, ctx->FontSize); // / this->_getScale();
            float currentHeight = 0.0f;

            while (textBegin < textEnd)
            {
                alignWrap = false;
                if (isElided)
                {
                    bool is_last_line = (currentHeight + 2.0f * ctx->FontSize) > availableHeight;
                    if (is_last_line)
                    {
                        const char* dots = this->getElidedTextStr().c_str();
                        _drawElidedText(ctx, cursor, textBegin, textEnd, dots, data.m_textMinimalWidth, textColor, alignment);
                        break;
                    }
                }

                // font->FontSize is the size of the font on startup of the application
                // ctx->FontSize is the current size of the font
                // It's important to correct width to the units when it was on startup, otherwise the word wrap is
                // broken when moving window to the second monitor.
                const char* textWrap = font->CalcWordWrapPosition(
                    font->LegacySize, textBegin, textEnd, data.m_textMinimalWidth * font->LegacySize / ctx->FontSize);

                // if no text-wrapping and \n in string, break into lines
                const char* newLine = strchr(textBegin, '\n');
                if (newLine && newLine < textWrap)
                {
                    textWrap = newLine + 1;
                    alignWrap = true;
                }

                // If the widget is too small to fit a single character, we should still advance the text.
                // Otherwise, this is an infinite loop. This occurs when the widget is visible attribute is set to
                // false.
                if (textWrap == textBegin)
                    textWrap = textBegin + 1;

                auto textSize = ImGui::CalcTextSize(textBegin, textWrap);

                float offset = _alignmentHOffset(alignment, textSize.x, data.m_textMinimalWidth);
                ImVec2 textPosition{ cursor.x + offset, cursor.y };

                drawList->AddText(font, ctx->FontSize, textPosition, textColor, textBegin, textWrap);

                int lines = 1;
                // There may be multi lines in previous text
                if (alignWrap == false)
                {
                    while (textBegin < textWrap)
                    {
                        if (*textBegin == '\n')
                            lines++;
                        textBegin++;
                    }
                }
                cursor.y += lines * ctx->FontSize;
                currentHeight += lines * ctx->FontSize;

                // Remove space from begin of the line.
                if (alignWrap == false)
                {
                    while (textWrap < textEnd)
                    {
                        const char c = *textWrap;
                        if (ImCharIsBlankA(c))
                        {
                            textWrap++;
                        }
                        else if (c == '\n')
                        {
                            textWrap++;
                            break;
                        }
                        else
                        {
                            break;
                        }
                    }
                }

                textBegin = textWrap;
            }
        }
        else
        {
            // We don't use ImGui::TextWrapped because it's not always the same size of ImGui::CalcTextSize. Other items
            // have an influence on ImGui::TextWrapped, we don't need it, we want to render it with predicted size.
            ImGui::RenderTextWrapped(cursor, this->getText().c_str(), nullptr, data.m_textMinimalWidth);
        }

        // It's not computed because it can be changed any frame.
        data.m_textMinimalSizeComputed = false;
    }
    else if (this->isElidedText())
    {
        auto textColor = ImGui::GetColorU32(ImGuiCol_Text);

        auto ctx = ImGui::GetCurrentContext();
        OMNIUI_ASSERT(ctx);
        const char* textBegin = this->getText().c_str();
        const char* textEnd = textBegin + this->getText().length();
        const char* dots = this->getElidedTextStr().c_str();
        _drawElidedText(ctx, cursor, textBegin, textEnd, dots, data.m_textMinimalWidth, textColor, alignment);

        // It's not computed because it can be changed any frame.
        data.m_textMinimalSizeComputed = false;
    }
    else
    {
        ImGui::RenderText(cursor, this->getText().c_str(), nullptr, this->isHideTextAfterHash());
    }

    this->_popFont();

    if (colorResolved)
    {
        ImGui::PopStyleColor();
    }
}

void Label::_computeTextSize(float width)
{
    auto& data = _getData<LabelData>();
    if (data.m_textMinimalSizeComputed)
    {
        return;
    }

    this->_pushFont(*this, this->_isParentCanvasFrame());

    ImVec2 textSize;
    if (this->isWordWrap())
    {
        textSize = ImGui::CalcTextSize(this->getText().c_str(), nullptr, false, width);

        if (this->isElidedText())
        {
            auto* ctx = ImGui::GetCurrentContext();

            // Number of lines that the available height can keep
            float linesCount = floorf(data.m_lastAvailableHeight / ctx->FontSize);

            // One line minimum
            linesCount = std::max(linesCount, 1.0f);

            textSize.y = std::max(std::min(textSize.y, linesCount * ctx->FontSize), ctx->FontSize);
        }
    }
    else
    {
        textSize = ImGui::CalcTextSize(this->getText().c_str());
        if (this->isElidedText())
        {
            textSize.x = std::min(textSize.x, width);
        }
    }

    this->_popFont();

    if (data.m_textMinimalWidth != textSize.x)
    {
        data.m_textMinimalWidth = textSize.x;
        this->forceWidthDirty(SizeDirtyReason::eSizeChanged);
    }

    if (data.m_textMinimalHeight != textSize.y)
    {
        data.m_textMinimalHeight = textSize.y;
        this->forceHeightDirty(SizeDirtyReason::eSizeChanged);
    }

    // TODO: Make it false each time the text is changed.
    data.m_textMinimalSizeComputed = true;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
