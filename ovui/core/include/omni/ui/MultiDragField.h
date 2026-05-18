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

#include "MultiField.h"

#include <cstdint>
#include <limits>
#include <memory>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

class FloatDrag;
class IntDrag;

/**
 * @brief The base class for MultiFloatDragField and MultiIntDragField. We need it because there classes are very
 * similar, so we can template them.
 *
 * @tparam T FloatDrag or IntDrag
 * @tparam U float or Int
 */
template <typename T, typename U>
class OMNIUI_CLASS_API MultiDragField : public AbstractMultiField
{
public:
    /**
     * @brief Reimplemented. Called by the model when the model value is changed.
     */
    OMNIUI_API
    void onModelUpdated(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item) override;

    // TODO: We are going to get min/max from the model.
    /**
     * @brief This property holds the drag's minimum value.
     */
    OMNIUI_PROPERTY(U, min, DEFAULT, std::numeric_limits<U>::lowest(), READ, getMin, WRITE, setMin, NOTIFY, setMinChangedFn);

    /**
     * @brief This property holds the drag's maximum value.
     */
    OMNIUI_PROPERTY(U, max, DEFAULT, std::numeric_limits<U>::max(), READ, getMax, WRITE, setMax, NOTIFY, setMaxChangedFn);

    /**
     * @brief This property controls the steping speed on the drag
     */
    OMNIUI_PROPERTY(float, step, DEFAULT, 0.001f, READ, getStep, WRITE, setStep, NOTIFY, setStepChangedFn);

protected:
    /**
     * @brief Constructs MultiDragField
     *
     * @param model The widget's model. If the model is not assigned, the default model is created.
     */
    OMNIUI_API
    MultiDragField(std::shared_ptr<AbstractItemModel> model = {});

    /**
     * @brief Create the widget with the model provided.
     */
    OMNIUI_API
    std::shared_ptr<Widget> _createField(std::shared_ptr<AbstractValueModel> model) override;

    /**
     * @brief Called to assign the new model to the widget created with `_createField`
     */
    OMNIUI_API
    void _setFieldModel(std::shared_ptr<Widget> widget, std::shared_ptr<AbstractValueModel> model) override;

private:
    struct MultiDragFieldData;

    /**
     * @brief Called when the min/max property is changed. It propagates min/max to children.
     */
    void _onMinMaxChanged();

    /**
     * @brief Called when the user changes step
     */
    void _onStepChanged(float step);
};

/**
 * @brief MultiFloatDragField is the widget that has a sub widget (FloatDrag) per model item.
 *
 * It's handy to use it for multi-component data, like for example, float3 or color.
 */
class OMNIUI_CLASS_API MultiFloatDragField : public MultiDragField<FloatDrag, double>
{
    OMNIUI_OBJECT(MultiFloatDragField)

protected:
    /**
     * @brief Constructs MultiFloatDragField
     *
     * @param model The widget's model. If the model is not assigned, the default model is created.
     */
    OMNIUI_API
    MultiFloatDragField(const std::shared_ptr<AbstractItemModel>& model = {})
        : MultiDragField<FloatDrag, double>{ model }
    {
    }
};

/**
 * @brief MultiIntDragField is the widget that has a sub widget (IntDrag) per model item.
 *
 * It's handy to use it for multi-component data, like for example, int3.
 */
class OMNIUI_CLASS_API MultiIntDragField : public MultiDragField<IntDrag, int32_t>
{
    OMNIUI_OBJECT(MultiIntDragField)

protected:
    /**
     * @brief Constructs MultiIntDragField
     *
     * @param model The widget's model. If the model is not assigned, the default model is created.
     */
    OMNIUI_API
    MultiIntDragField(const std::shared_ptr<AbstractItemModel>& model = {}) : MultiDragField<IntDrag, int32_t>{ model }
    {
    }
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
