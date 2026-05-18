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

#include <cstdint>
#include <memory>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The abstract widget that is base for drags and sliders.
 */
class OMNIUI_CLASS_API AbstractSlider : public Widget, public ValueModelHelper, public FontHelper
{
public:
    // TODO: this need to be moved to be a Header like Alignment
    enum class DrawMode : uint8_t
    {
        // filled mode will render the left portion of the slider with filled solid color from styling
        eFilled = 0,
        // handle mode draw a knobs at the slider position
        eHandle,
        // The Slider doesn't display either Handle or Filled Rect
        eDrag
    };

    OMNIUI_API
    ~AbstractSlider() override;

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

protected:
    OMNIUI_API
    AbstractSlider(std::shared_ptr<AbstractValueModel> model = {}, WidgetData* data = nullptr);

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

    /**
     * @brief Should be called before editing the model to make sure model::beginEdit called properly.
     */
    OMNIUI_API
    virtual void _beginModelChange();

    /**
     * @brief Should be called after editing the model to make sure model::endEdit called properly.
     */
    OMNIUI_API
    virtual void _endModelChange();

    /**
     * @brief the ration calculation is requiere to draw the Widget as Gauge, it is calculated with Min/Max & Value
     */
    virtual float _getValueRatio() = 0;

    // True if the mouse is down
    bool m_editActive = false;

private:
    /**
     * @brief _drawContent sets everything up including styles and fonts and calls this method.
     */
    virtual void _drawUnderlyingItem() = 0;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
