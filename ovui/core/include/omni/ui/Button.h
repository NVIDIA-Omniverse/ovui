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

#include "InvisibleButton.h"
#include "Stack.h"

#include <memory>
#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

class Label;
class Rectangle;
class Image;

/**
 * @brief The Button widget provides a command button.
 *
 * The command button, is perhaps the most commonly used widget in any graphical user interface. Click a button to
 * execute a command. It is rectangular and typically displays a text label describing its action.
 */
class OMNIUI_CLASS_API Button : public InvisibleButton
{
    OMNIUI_OBJECT(Button)

public:
    OMNIUI_API
    ~Button() override;

    OMNIUI_API
    void destroy() override;

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
     * @brief Reimplemented. Something happened with the style or with the parent style. We need to gerenerate the
     * cache.
     */
    OMNIUI_API
    void onStyleUpdated() override;

    /**
     * @brief Reimplemented. It's called when the style is changed. It should be propagated to children to make the
     * style cached and available to children.
     */
    OMNIUI_API
    void cascadeStyle() override;

    /**
     * @brief This property holds the button's text.
     */
    OMNIUI_PROPERTY(std::string, text, READ, getText, WRITE, setText, NOTIFY, setTextChangedFn);

    /**
     * @brief This property holds the button's optional image URL.
     */
    OMNIUI_PROPERTY(std::string, imageUrl, READ, getImageUrl, WRITE, setImageUrl, NOTIFY, setImageUrlChangedFn);

    /**
     * @brief This property holds the width of the image widget. Do not use this function to find the width of the
     * image.
     */
    OMNIUI_PROPERTY(Length,
                    imageWidth,
                    DEFAULT,
                    Fraction{ 1.0f },
                    READ,
                    getImageWidth,
                    WRITE,
                    setImageWidth,
                    NOTIFY,
                    setImageWidthChangedFn);

    /**
     * @brief This property holds the height of the image widget. Do not use this function to find the height of the
     * image.
     */
    OMNIUI_PROPERTY(Length,
                    imageHeight,
                    DEFAULT,
                    Fraction{ 1.0f },
                    READ,
                    getImageHeight,
                    WRITE,
                    setImageHeight,
                    NOTIFY,
                    setImageHeightChangedFn);

    /**
     * @brief Sets a non-stretchable space in points between image and text.
     */
    OMNIUI_PROPERTY(float, spacing, DEFAULT, 0.0f, READ, getSpacing, WRITE, setSpacing, NOTIFY, setSpacingChangedFn);

protected:
    struct ButtonData;

    /**
     * @brief Construct a button with a text on it.
     *
     * @param text The text for the button to use.
     */
    OMNIUI_API
    Button(const std::string& text = {}, ButtonData* = nullptr);

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

private:

    /**
     * @brief Compute the size of the button and save result to the private members.
     */
    void _computeButtonSize();

    /**
     * @brief Return the name of the child widget. Basically it creates a string like this: "Button.{childType}".
     */
    std::string _childTypeName(const std::string& childType) const;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
