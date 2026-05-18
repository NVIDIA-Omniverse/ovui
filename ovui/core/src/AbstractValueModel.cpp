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

#include "platform/Log.h"
#include <omni/ui/AbstractValueModel.h>
#include <omni/ui/Profile.h>
#include <omni/ui/ValueModelHelper.h>

OMNIUI_NAMESPACE_OPEN_SCOPE

AbstractValueModel::AbstractValueModel() = default;

AbstractValueModel::~AbstractValueModel()
{
    std::vector<ValueModelHelper*> buffer{ m_widgets.begin(), m_widgets.end() };

    for (auto widget : buffer)
    {
        widget->setModel({});
    }
}

void AbstractValueModel::beginEdit()
{
}

void AbstractValueModel::endEdit()
{
}

void AbstractValueModel::subscribe(ValueModelHelper* widget)
{
    m_widgets.insert(widget);
}

void AbstractValueModel::unsubscribe(ValueModelHelper* widget)
{
    m_widgets.erase(widget);
}

template <typename T>
static void invokeCallbacks(AbstractValueModel& model, const T& callbacks)
{
    // Use a simpler index-based for-loop in case the underlying callbacks is re-allocated during the callback.
    // This relies on the fact that if removeXXXFn is called during callback, it will not shrink callback vector.
    // The current pattern also relies on a reference to the current callback rather than a copy/clone of the shared_ptr
    // because it is not used after callback returns.
    for (size_t i = 0, n = callbacks.size(); i < n; ++i)
    {
        if (auto&& callback = callbacks[i])
        {
            callback(&model);
        }
    }
}

uint32_t AbstractValueModel::addValueChangedFn(std::function<void(const AbstractValueModel*)> fn)
{
    uint32_t id = static_cast<uint32_t>(m_valueChangedCallbacks.size());
    m_valueChangedCallbacks.emplace_back(std::move(fn));
    return id;
}

void AbstractValueModel::removeValueChangedFn(uint32_t id)
{
    // We don't remove it to keep the ids that we already returned. Instead, we make this function NULL, so it will be skipped.
    if (id < m_valueChangedCallbacks.size())
    {
        m_valueChangedCallbacks[id] = nullptr;
    }
    else
    {
        OMNIUI_LOG_ERROR("ValueChanged subscription was invalid");
    }
}

uint32_t AbstractValueModel::addBeginEditFn(std::function<void(const AbstractValueModel*)> fn)
{
    uint32_t id = static_cast<uint32_t>(m_beginEditCallbacks.size());
    m_beginEditCallbacks.emplace_back(std::move(fn));
    return id;
}

void AbstractValueModel::removeBeginEditFn(uint32_t id)
{
    // We don't remove it to keep the ids that we already returned. Instead, we make this function NULL, so it will be
    // skipped.
    if (id < m_beginEditCallbacks.size())
    {
        m_beginEditCallbacks[id] = nullptr;
    }
    else
    {
        OMNIUI_LOG_ERROR("BeginEdit subscription was invalid");
    }
}

uint32_t AbstractValueModel::addEndEditFn(std::function<void(const AbstractValueModel*)> fn)
{
    uint32_t id = static_cast<uint32_t>(m_endEditCallbacks.size());
    m_endEditCallbacks.emplace_back(std::move(fn));
    return id;
}

void AbstractValueModel::removeEndEditFn(uint32_t id)
{
    // We don't remove it to keep the ids that we already returned. Instead, we make this function NULL, so it will be
    // skipped.
    if (id < m_endEditCallbacks.size())
    {
        m_endEditCallbacks[id] = nullptr;
    }
    else
    {
        OMNIUI_LOG_ERROR("EndEdit subscription was invalid");
    }
}

void AbstractValueModel::processBeginEditCallbacks()
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;
    this->beginEdit();

    invokeCallbacks(*this, m_beginEditCallbacks);
}

void AbstractValueModel::processEndEditCallbacks()
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    // XXX: AbstractItemModel::processEndEditCallbacks reverses this->endEdit and callback invocation order.
    invokeCallbacks(*this, m_endEditCallbacks);

    this->endEdit();
}

void AbstractValueModel::_valueChanged()
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;
    // Notify everyone the value is changed
    for (auto widget : m_widgets)
    {
        widget->onModelUpdated();
    }

    invokeCallbacks(*this, m_valueChangedCallbacks);
}

template <>
bool AbstractValueModel::getValue<bool>() const
{
    return this->getValueAsBool();
}

template <>
double AbstractValueModel::getValue<double>() const
{
    return this->getValueAsFloat();
}

template <>
int64_t AbstractValueModel::getValue<int64_t>() const
{
    return this->getValueAsInt();
}

template <>
std::string AbstractValueModel::getValue<std::string>() const
{
    return this->getValueAsString();
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
