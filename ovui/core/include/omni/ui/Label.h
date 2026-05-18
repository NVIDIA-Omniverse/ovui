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

#include "Alignment.h"
#include "FontHelper.h"
#include "Widget.h"

#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The Label widget provides a text to display.
 *
 * Label is used for displaying text. No additional to Widget user interaction functionality is provided.
 */
class OMNIUI_CLASS_API Label : public Widget, public FontHelper
{
    OMNIUI_OBJECT(Label)

public:
    OMNIUI_API
    ~Label() override;

    /**
     * @brief Reimplemented the method to indicate the width hint that represents the preferred size of the widget.
     * Currently this widget can't be smaller than the size of the text.
     *
     * @see Widget::setComputedContentWidth
     */
    OMNIUI_API
    void setComputedContentWidth(float width) override;

    /**
     * @brief Reimplemented the method to indicate the height hint that represents the preferred size of the widget.
     * Currently this widget can't be smaller than the size of the text.
     *
     * @see Widget::setComputedContentHeight
     */
    OMNIUI_API
    void setComputedContentHeight(float height) override;

    /**
     * @brief Reimplemented. Something happened with the style or with the parent style. We need to update the saved
     * font.
     */
    OMNIUI_API
    void onStyleUpdated() override;

    /**
     * @brief Return the exact width of the content of this label. Computed content width is a size hint and may be
     * bigger than the text in the label
    */
    OMNIUI_API
    float exactContentWidth();

    /**
     * @brief Return the exact height of the content of this label. Computed content height is a size hint and may be
     * bigger than the text in the label
    */
    OMNIUI_API
    float exactContentHeight();

    /**
     * @brief This property holds the label's text.
     */
    OMNIUI_PROPERTY(std::string, text, READ, getText, WRITE, setText, NOTIFY, setTextChangedFn);

    /**
     * @brief This property holds the label's word-wrapping policy
     * If this property is true then label text is wrapped where necessary at word-breaks; otherwise it is not wrapped
     * at all.
     * By default, word wrap is disabled.
     */
    OMNIUI_PROPERTY(bool, wordWrap, DEFAULT, false, READ, isWordWrap, WRITE, setWordWrap);

    /**
     * @brief When the text of a big length has to be displayed in a small area, it can be useful to give the user a
     * visual hint that not all text is visible. Label can elide text that doesn't fit in the area. When this property
     * is true, Label elides the middle of the last visible line and replaces it with "...".
     */
    OMNIUI_PROPERTY(bool, elidedText, DEFAULT, false, READ, isElidedText, WRITE, setElidedText);

    /**
     * @brief Customized elidedText string when elidedText is True, default is "...".
     */
    OMNIUI_PROPERTY(std::string, elidedTextStr, DEFAULT, "...", READ, getElidedTextStr, WRITE, setElidedTextStr);

    /**
     * @brief This property holds the alignment of the label's contents
     * By default, the contents of the label are left-aligned and vertically-centered.
     */
    OMNIUI_PROPERTY(Alignment, alignment, DEFAULT, Alignment::eLeftCenter, READ, getAlignment, WRITE, setAlignment);

    /**
     * @brief Hide anything after a '##' string or not
     */
    OMNIUI_PROPERTY(bool, hideTextAfterHash, DEFAULT, true, READ, isHideTextAfterHash, WRITE, setHideTextAfterHash);

protected:
    /**
     * @brief Create a label with the given text.
     *
     * @param text The text for the label.
     */
    OMNIUI_API
    Label(const std::string& text);

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

private:
    struct LabelData;

    /**
     * @brief Compute the size of the text and save result to the private members.
     *
     * @param width Is used for wrapping. If wrapping enabled, it has the maximum allowed text width. If there is no
     * wrapping, it's ignored.
     */
    void _computeTextSize(float width);
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
