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

#include <omni/ui/FloatDrag.h>
#include <omni/ui/IntDrag.h>
#include <omni/ui/MultiDragField.h>
#include <omni/ui/SimpleListModel.h>

#include "AbstractMultiFieldData.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

template <typename T, typename U>
struct MultiDragField<T,U>::MultiDragFieldData : public AbstractMultiField::AbstractMultiFieldData
{
    std::vector<std::weak_ptr<T>> m_drags;
};

template <typename T, typename U>
MultiDragField<T, U>::MultiDragField(std::shared_ptr<AbstractItemModel> model)
    : AbstractMultiField(std::move(model), new MultiDragFieldData)
{
    using std::placeholders::_1;

    if (!static_cast<bool>(getModel()))
    {
        // If there is no model, create a simple 3 item list
        this->setModel(SimpleListModel::create(std::vector<U>{ { U{ 0 }, U{ 0 }, U{ 0 } } }));
    }
    else
    {
        // We can't call it from the base class because it's not possible to call inherited methods in the constructor.
        this->onModelUpdated(nullptr);
    }

    this->setMinChangedFn(std::bind(&MultiDragField<T, U>::_onMinMaxChanged, this));
    this->setMaxChangedFn(std::bind(&MultiDragField<T, U>::_onMinMaxChanged, this));
    this->setStepChangedFn(std::bind(&MultiDragField<T, U>::_onStepChanged, this, _1));
}

template <typename T, typename U>
void MultiDragField<T, U>::onModelUpdated(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
    if (item == nullptr)
    {
        _getData<MultiDragFieldData>().m_drags.clear();
    }

    AbstractMultiField::onModelUpdated(item);
}

template <typename T, typename U>
std::shared_ptr<Widget> MultiDragField<T, U>::_createField(std::shared_ptr<AbstractValueModel> model)
{
    auto drag = T::create(std::move(model));
    drag->setMin(this->getMin());
    drag->setMax(this->getMax());
    _getData<MultiDragFieldData>().m_drags.emplace_back(drag);
    return drag;
}

template <typename T, typename U>
void MultiDragField<T, U>::_setFieldModel(std::shared_ptr<Widget> widget,
                                          std::shared_ptr<AbstractValueModel> model)
{
    std::static_pointer_cast<T>(widget)->setModel(std::move(model));
}

template <typename T, typename U>
void MultiDragField<T, U>::_onMinMaxChanged()
{
    U min = this->getMin();
    U max = this->getMax();

    for (const auto& weakDrag : _getData<MultiDragFieldData>().m_drags)
    {
        auto drag = weakDrag.lock();
        if (!drag)
        {
            continue;
        }

        drag->setMin(min);
        drag->setMax(max);
    }
}

template <typename T, typename U>
void MultiDragField<T, U>::_onStepChanged(float step)
{
    for (auto& child : _getChildren())
    {
        auto drag = std::dynamic_pointer_cast<FloatDrag>(child);
        if (drag)
        {
            drag->setStep(step);
        }
    }
}

// Symbols for <FloatDrag, double> and <IntDrag, int32_t>
template MultiDragField<FloatDrag, double>::MultiDragField(std::shared_ptr<AbstractItemModel> model);
template void MultiDragField<FloatDrag, double>::onModelUpdated(
    const std::shared_ptr<const AbstractItemModel::AbstractItem>& item);
template std::shared_ptr<Widget> MultiDragField<FloatDrag, double>::_createField(std::shared_ptr<AbstractValueModel> model);
template void MultiDragField<FloatDrag, double>::_setFieldModel(std::shared_ptr<Widget> widget, std::shared_ptr<AbstractValueModel> model);
template void MultiDragField<FloatDrag, double>::_onMinMaxChanged();
template void MultiDragField<FloatDrag, double>::_onStepChanged(float step);
template MultiDragField<IntDrag, int32_t>::MultiDragField(std::shared_ptr<AbstractItemModel> model);
template void MultiDragField<IntDrag, int32_t>::onModelUpdated(
    const std::shared_ptr<const AbstractItemModel::AbstractItem>& item);
template std::shared_ptr<Widget> MultiDragField<IntDrag, int32_t>::_createField(std::shared_ptr<AbstractValueModel> model);
template void MultiDragField<IntDrag, int32_t>::_setFieldModel(std::shared_ptr<Widget> widget, std::shared_ptr<AbstractValueModel> model);
template void MultiDragField<IntDrag, int32_t>::_onMinMaxChanged();
template void MultiDragField<IntDrag, int32_t>::_onStepChanged(float step);

OMNIUI_NAMESPACE_CLOSE_SCOPE
