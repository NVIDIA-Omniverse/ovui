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

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The slider is the classic widget for controlling a bounded value. It lets the user move a slider handle along
 * a horizontal groove and translates the handle's position into an integer value within the legal range.
 */
template <typename T>
class OMNIUI_CLASS_API CommonIntSlider : public AbstractSlider
{
public:
    /**
     * @brief Reimplemented the method from ValueModelHelper that is called when the model is changed.
     */
    OMNIUI_API
    void onModelUpdated() override;

    /**
     * @brief This property holds the slider's minimum value.
     */
    OMNIUI_PROPERTY(T, min, DEFAULT, 0, READ, getMin, WRITE, setMin);

    /**
     * @brief This property holds the slider's maximum value.
     */
    OMNIUI_PROPERTY(T, max, DEFAULT, 100, READ, getMax, WRITE, setMax);

protected:
    OMNIUI_API
    CommonIntSlider(std::shared_ptr<AbstractValueModel> model = {});

    /**
     * @brief the ration calculation is requiere to draw the Widget as Gauge, it is calculated with Min/Max & Value
     */
    virtual float _getValueRatio() override;

private:
    struct IntSliderData;
    /**
     * @brief Reimplemented. _drawContent sets everything up including styles and fonts and calls this method.
     */
    void _drawUnderlyingItem() override;

    /**
     * @brief It has to run a very low level function to call the widget.
     */
    virtual bool _drawUnderlyingItem(T* value, T min, T max) = 0;
};

/**
 * @brief The slider is the classic widget for controlling a bounded value. It lets the user move a slider handle along
 * a horizontal groove and translates the handle's position into an integer value within the legal range.
 */
class OMNIUI_CLASS_API IntSlider : public CommonIntSlider<int64_t>
{
    OMNIUI_OBJECT(IntSlider)

protected:
    /**
     * @brief Constructs IntSlider
     *
     * @param model The widget's model. If the model is not assigned, the default model is created.
     */
    OMNIUI_API
    IntSlider(std::shared_ptr<AbstractValueModel> model = {}) : CommonIntSlider<int64_t>(std::move(model))
    {
    }

private:
    /**
     * @brief Runs a very low level function to call the widget.
     */
    OMNIUI_API
    virtual bool _drawUnderlyingItem(int64_t* value, int64_t min, int64_t max) override;
};

/**
 * @brief The slider is the classic widget for controlling a bounded value. It lets the user move a slider handle along
 * a horizontal groove and translates the handle's position into an integer value within the legal range.
 *
 * The difference with IntSlider is that UIntSlider has unsigned min/max.
 */
class OMNIUI_CLASS_API UIntSlider : public CommonIntSlider<uint64_t>
{
    OMNIUI_OBJECT(UIntSlider)

protected:
    /**
     * @brief Constructs UIntSlider
     *
     * @param model The widget's model. If the model is not assigned, the default model is created.
     */
    OMNIUI_API
    UIntSlider(std::shared_ptr<AbstractValueModel> model = {}) : CommonIntSlider<uint64_t>(std::move(model))
    {
    }

private:
    /**
     * @brief Runs a very low level function to call the widget.
     */
    OMNIUI_API
    virtual bool _drawUnderlyingItem(uint64_t* value, uint64_t min, uint64_t max) override;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
