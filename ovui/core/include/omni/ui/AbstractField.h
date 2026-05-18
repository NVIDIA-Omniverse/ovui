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

#include "FontHelper.h"
#include "ValueModelHelper.h"
#include "Widget.h"

#include <cstdint>
#include <memory>
#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

class Rectangle;

/**
 * @brief The abstract widget that is base for any field, which is a one-line text editor.
 *
 * A field allows the user to enter and edit a single line of plain text. It's implemented using the model-view pattern
 * and uses AbstractValueModel as the central component of the system.
 */
class OMNIUI_CLASS_API AbstractField : public Widget, public ValueModelHelper, public FontHelper
{
public:
    OMNIUI_API
    ~AbstractField() override;

    /**
     * @brief Reimplemented the method to indicate the width hint that represents the preferred size of the widget.
     *
     * @see Widget::setComputedContentWidth
     */
    OMNIUI_API
    void setComputedContentWidth(float width) override;

    /**
     * @brief Reimplemented the method to indicate the height hint that represents the preferred size of the widget.
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
     * @brief Reimplemented the method from ValueModelHelper that is called when the model is changed.
     *
     * TODO: We can avoid it if we create templated ValueModelHelper that manages data.
     */
    OMNIUI_API
    void onModelUpdated() override;

    /**
     * @brief Puts cursor to this field or removes focus if `focus` is false.
     */
    OMNIUI_API
    void focusKeyboard(bool focus = true);

protected:
    struct AbstractFieldData;

    OMNIUI_API
    AbstractField(std::shared_ptr<AbstractValueModel> model = {}, AbstractFieldData* data = nullptr);

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

private:
    /**
     * @brief It's necessary to implement it to convert model to string buffer that is displayed by the field. It's
     * possible to use it for setting the string format.
     */
    virtual std::string _generateTextForField() = 0;

    /**
     * @brief Set/get the field data and the state on a very low level of the underlying system.
     */
    virtual void _updateSystemText(void*) = 0;

    /**
     * @brief Determines the flags that are used in the underlying system widget.
     */
    virtual int32_t _getSystemFlags() const = 0;

    /**
     * @brief Internal private callback. It's called when the internal text buffer needs to change the size.
     */
    static int32_t _onInputTextActive(void*);
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
