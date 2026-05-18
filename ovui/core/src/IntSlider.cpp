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
#include <imgui/imgui_internal.h>
#include <omni/ui/IntSlider.h>
#include <omni/ui/SimpleNumericModel.h>

#include "WidgetData.h"

#include <algorithm>

OMNIUI_NAMESPACE_OPEN_SCOPE

template <typename T>
struct CommonIntSlider<T>::IntSliderData : public Widget::WidgetData
{
    // The cached state of the slider.
    T m_valueCache = 0;
};

template <typename T>
CommonIntSlider<T>::CommonIntSlider(std::shared_ptr<AbstractValueModel> model)
    : AbstractSlider(std::move(model), new IntSliderData)
{
    if (!static_cast<bool>(getModel()))
    {
        // If there is no model, create a simple string one.
        this->setModel(SimpleIntModel::create());
    }
    else
    {
        // We can't call it from the base class because it's not possible to call inherited methods in the constructor.
        this->onModelUpdated();
    }
}

template <typename T>
float CommonIntSlider<T>::_getValueRatio()
{
    T min = this->getMin();
    T max = this->getMax();
    T value = _getData<IntSliderData>().m_valueCache;

    // Handle the case where min equals max to prevent division by zero
    if (min == max)
        return 0.0f;

    // Check if we're dealing with the full range of the integer type
    bool isFullRange = (min == std::numeric_limits<T>::lowest() && max == std::numeric_limits<T>::max());

    // For signed types (int64_t) with full range
    if (isFullRange && std::is_same<T, int64_t>::value)
    {
        // Handle negative and positive ranges separately to avoid overflow
        if (value < 0)
        {
            double negativeRange = static_cast<double>(-std::numeric_limits<int64_t>::lowest());
            return static_cast<float>(0.5 - static_cast<double>(value) / (negativeRange * 2.0));
        }
        else
        {
            double positiveRange = static_cast<double>(std::numeric_limits<int64_t>::max()) + 1.0;
            return static_cast<float>(0.5 + static_cast<double>(value) / (positiveRange * 2.0));
        }
    }

    // For unsigned types (uint64_t) with full range
    if (isFullRange && std::is_same<T, uint64_t>::value)
    {
        double fullRange = static_cast<double>(std::numeric_limits<uint64_t>::max());
        return static_cast<float>(static_cast<double>(value) / fullRange);
    }

    // For all other cases, use double to avoid potential overflow
    return static_cast<float>((static_cast<double>(value) - static_cast<double>(min)) /
                             (static_cast<double>(max) - static_cast<double>(min)));
}

template <typename T>
void CommonIntSlider<T>::onModelUpdated()
{
    const auto& model = this->getModel();
    if (OMNIUI_UNLIKELY(static_cast<bool>(model) == false))
    {
        OMNIUI_LOG_ERROR("CommonIntSlider::onModelUpdated had no model");
        return;
    }

    _getData<IntSliderData>().m_valueCache = static_cast<T>(model->template getValue<int64_t>());

    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

template <typename T>
void CommonIntSlider<T>::_drawUnderlyingItem()
{
    T value = _getData<IntSliderData>().m_valueCache;
    bool result = this->_drawUnderlyingItem(&value, this->getMin(), this->getMax());

    this->_beginModelChange();

    if (result)
    {
        auto model = this->getModel();
        if (OMNIUI_LIKELY(static_cast<bool>(model)))
        {
            // Trying to set the value. If the model accepts it, it will call onModelUpdated and update m_textBuffer.
            model->setValue(static_cast<int64_t>(value));
        }
        else
        {
            OMNIUI_LOG_ERROR("CommonIntSlider::_drawUnderlyingItem had no model");
        }
    }

    this->_endModelChange();
}

bool IntSlider::_drawUnderlyingItem(int64_t* value, int64_t min, int64_t max)
{
    return ImGui::SliderScalar("##hidelabel", ImGuiDataType_S64, value, &min, &max);
}

bool UIntSlider::_drawUnderlyingItem(uint64_t* value, uint64_t min, uint64_t max)
{
    return ImGui::SliderScalar("##hidelabel", ImGuiDataType_U64, value, &min, &max);
}

template OMNIUI_API CommonIntSlider<int64_t>::CommonIntSlider(std::shared_ptr<AbstractValueModel> model);
template OMNIUI_API CommonIntSlider<uint64_t>::CommonIntSlider(std::shared_ptr<AbstractValueModel> model);
template OMNIUI_API float CommonIntSlider<int64_t>::_getValueRatio();
template OMNIUI_API float CommonIntSlider<uint64_t>::_getValueRatio();
template OMNIUI_API void CommonIntSlider<int64_t>::onModelUpdated();
template OMNIUI_API void CommonIntSlider<uint64_t>::onModelUpdated();
template OMNIUI_API void CommonIntSlider<int64_t>::_drawUnderlyingItem();
template OMNIUI_API void CommonIntSlider<uint64_t>::_drawUnderlyingItem();

OMNIUI_NAMESPACE_CLOSE_SCOPE
