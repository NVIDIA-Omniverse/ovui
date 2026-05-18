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

#include "Widget.h"

#include <float.h>
#include <functional>
#include <string>
#include <utility>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The Plot widget provides a line/histogram to display.
 */
class OMNIUI_CLASS_API Plot : public Widget
{
    OMNIUI_OBJECT(Plot)

    using PlotData1D = std::vector<float>;
    using PlotData2D = std::vector<std::pair<float, float>>;

public:
    OMNIUI_API
    ~Plot() override;

    /**
     * @brief This type is used to determine the type of the image.
     */
    enum class Type
    {
        eLine,
        eHistogram,
        eLine2D,
    };

    /**
     * @brief Reimplemented the method to indicate the height hint that represents the preferred size of the widget.
     * Currently this widget can't be smaller than 1 pixel
     *
     * @see Widget::setComputedContentHeight
     */
    OMNIUI_API
    void setComputedContentHeight(float height) override;

    /**
     * @brief Sets the function that will be called when when data required.
     */
    OMNIUI_API
    virtual void setDataProviderFn(std::function<float(int)> fn, int valuesCount);

    /**
     * @brief Sets the image data value.
     */
    OMNIUI_API
    virtual void setData(PlotData1D valueList);

    /**
     * @brief Sets the 2d data. X coordinate helps to put the point at the exact
     * position. Useful when the points are at different distance.
     */
    OMNIUI_API
    virtual void setXYData(PlotData2D valueList);

    /**
     * @brief This property holds the type of the image, can only be line or histogram.
     * By default, the type is line.
     */
    OMNIUI_PROPERTY(Type, type, DEFAULT, Type::eLine, READ, getType, WRITE, setType);

    /**
     * @brief This property holds the min scale values.
     * By default, the value is FLT_MAX.
     */
    OMNIUI_PROPERTY(float, scaleMin, DEFAULT, FLT_MAX, READ, getScaleMin, WRITE, setScaleMin);

    /**
     * @brief This property holds the max scale values.
     * By default, the value is FLT_MAX.
     */
    OMNIUI_PROPERTY(float, scaleMax, DEFAULT, FLT_MAX, READ, getScaleMax, WRITE, setScaleMax);

    /**
     * @brief This property holds the value offset.
     * By default, the value is 0.
     */
    OMNIUI_PROPERTY(int, valueOffset, DEFAULT, 0, READ, getValueOffset, WRITE, setValueOffset);

    /**
     * @brief This property holds the stride to get value list.
     * By default, the value is 1.
     */
    OMNIUI_PROPERTY(int, valueStride, DEFAULT, 1, READ, getValueStride, WRITE, setValueStride);

    /**
     * @brief This property holds the title of the image.
     */
    OMNIUI_PROPERTY(std::string, title, DEFAULT, "", READ, getTitle, WRITE, setTitle);

protected:
    /**
     * @brief Construct Plot
     *
     * @param type The type of the image, can be line or histogram.
     * @param scaleMin The minimal scale value.
     * @param scaleMax The maximum scale value.
     * @param valueList The list of values to draw the image.
     */
    OMNIUI_API
    Plot(Type type, float scaleMin, float scaleMax, PlotData1D);

    OMNIUI_API
    Plot(Type type, float scaleMin, float scaleMax, PlotData2D valueList);

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

private:
    struct PlotData;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
