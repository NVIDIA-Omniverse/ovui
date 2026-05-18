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

#include "ItemModelHelper.h"
#include "Widget.h"

#include <cstdint>
#include <memory>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

class AbstractItemModel;
class AbstractValueModel;
class ValueModelHelper;
class Stack;

/**
 * @brief AbstractMultiField is the abstract class that has everything to create a custom widget per model item.
 *
 * The class that wants to create multiple widgets per item needs to reimplement the method _createField.
 */
class OMNIUI_CLASS_API AbstractMultiField : public Widget, public ItemModelHelper
{
    OMNIUI_OBJECT(AbstractMultiField)

public:
    OMNIUI_API
    ~AbstractMultiField() override;

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
     * @brief Reimplemented. Called by the model when the model value is changed.
     *
     * @param item The item in the model that is changed. If it's NULL, the root is chaged.
     */
    OMNIUI_API
    void onModelUpdated(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item) override;

    /**
     * @brief The max number of fields in a line.
     */
    OMNIUI_PROPERTY(
        uint8_t, columnCount, DEFAULT, 4, READ, getColumnCount, WRITE, setColumnCount, NOTIFY, setColumnCountChangedFn);

    /**
     * @brief Sets a non-stretchable horizontal space in pixels between child fields.
     */
    OMNIUI_PROPERTY(float, hSpacing, DEFAULT, 0.0f, READ, getHSpacing, WRITE, setHSpacing, NOTIFY, setHSpacingChangedFn);

    /**
     * @brief Sets a non-stretchable vertical space in pixels between child fields.
     */
    OMNIUI_PROPERTY(float, vSpacing, DEFAULT, 0.0f, READ, getVSpacing, WRITE, setVSpacing, NOTIFY, setVSpacingChangedFn);

protected:
    struct AbstractMultiFieldData;

    /**
     * Constructor.
     */
    OMNIUI_API
    AbstractMultiField(std::shared_ptr<AbstractItemModel> model = {}, AbstractMultiFieldData* data = nullptr);

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

    /**
     * @brief It's necessary to implement this method to create a custom widget per model item. It creates the widget
     * with the model provided and returns it.
     */
    OMNIUI_API
    virtual std::shared_ptr<Widget> _createField(std::shared_ptr<AbstractValueModel> model);

    /**
     * @brief Called to assign the new model to the widget created with `_createField`
     */
    OMNIUI_API
    virtual void _setFieldModel(std::shared_ptr<Widget> widget, std::shared_ptr<AbstractValueModel> model);

    OMNIUI_API
    const std::vector<std::shared_ptr<Widget>>& _getChildren() const;

private:
    /**
     * @brief Called when the spacing property is changed. It propagates spacing to children.
     */
    void _onSpacingChanged();

    /**
     * @brief Called when the column_count property is changed.
     */
    void _onColumnCountChanged();
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
