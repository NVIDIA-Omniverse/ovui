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

#include "AbstractSlider.h"

#include <cstdint>
#include <memory>
#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The slider is the classic widget for controlling a bounded value. It lets the user move a slider handle along
 * a horizontal groove and translates the handle's position into a float value within the legal range.
 */
class OMNIUI_CLASS_API FloatSlider : public AbstractSlider
{
    OMNIUI_OBJECT(FloatSlider)

public:
    /**
     * @brief Reimplemented the method from ValueModelHelper that is called when the model is changed.
     */
    OMNIUI_API
    void onModelUpdated() override;

    /**
     * @brief Get the format string for the given value. The number should be in the format of `0.0` and the length of
     * the formed string should be minimal.
     */
    static const char* getFormatString(double value, uint32_t maxSymbols = 5);

    /**
     * @brief This property holds the slider's minimum value.
     */
    OMNIUI_PROPERTY(double, min, DEFAULT, 0.0f, READ, getMin, WRITE, setMin);

    /**
     * @brief This property holds the slider's maximum value.
     */
    OMNIUI_PROPERTY(double, max, DEFAULT, 1.0f, READ, getMax, WRITE, setMax);

    /**
     * @brief This property controls the steping speed on the drag
     */
    OMNIUI_PROPERTY(float, step, DEFAULT, 0.01f, READ, getStep, WRITE, setStep);

    /**
     * @brief This property overrides automatic formatting if needed
     */
    OMNIUI_PROPERTY(std::string, format, DEFAULT, "", READ, getFormat, WRITE, setFormat);

    /**
     * @brief This property holds the slider value's float precision
     */
    OMNIUI_PROPERTY(uint32_t, precision, DEFAULT, 5, READ, getPrecision, WRITE, setPrecision);

protected:
    /**
     * @brief Construct FloatSlider
     */
    OMNIUI_API
    FloatSlider(std::shared_ptr<AbstractValueModel> model = {});

    /**
     * @brief the ration calculation is requiere to draw the Widget as Gauge, it is calculated with Min/Max & Value
     */
    virtual float _getValueRatio() override;

private:
    struct FloatSliderData;

    /**
     * @brief Reimplemented. _drawContent sets everything up including styles and fonts and calls this method.
     */
    void _drawUnderlyingItem() override;

    /**
     * @brief It has to run a very low level function to call the widget.
     */
    virtual bool _drawUnderlyingItem(double* value, double min, double max);
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
