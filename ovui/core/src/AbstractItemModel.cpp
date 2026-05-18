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
#include <omni/ui/AbstractItemModel.h>
#include <omni/ui/ItemModelHelper.h>
#include <omni/ui/Profile.h>


OMNIUI_NAMESPACE_OPEN_SCOPE

AbstractItemModel::AbstractItemModel() = default;
AbstractItemModel::~AbstractItemModel() = default;

bool AbstractItemModel::canItemHaveChildren(const std::shared_ptr<const AbstractItemModel::AbstractItem>& parentItem)
{
    return !this->getItemChildren(parentItem).empty();
}

std::shared_ptr<const AbstractItemModel::AbstractItem> AbstractItemModel::appendChildItem(
    const std::shared_ptr<const AbstractItemModel::AbstractItem>& parentItem, std::shared_ptr<AbstractValueModel> model)
{
    return nullptr;
}

void AbstractItemModel::removeItem(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
}

void AbstractItemModel::beginEdit(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
}

void AbstractItemModel::endEdit(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
}

bool AbstractItemModel::dropAccepted(const std::shared_ptr<const AbstractItemModel::AbstractItem>& itemTarget,
                                     const std::shared_ptr<const AbstractItemModel::AbstractItem>& itemSource,
                                     int32_t dropLocation)
{
    return true;
}

bool AbstractItemModel::dropAccepted(const std::shared_ptr<const AbstractItemModel::AbstractItem>& itemTarget,
                                     const char* source,
                                     int32_t dropLocation)
{
    return true;
}

void AbstractItemModel::drop(const std::shared_ptr<const AbstractItemModel::AbstractItem>& itemTarget,
                             const std::shared_ptr<const AbstractItemModel::AbstractItem>& itemSource,
                             int32_t dropLocation)
{
}

void AbstractItemModel::drop(const std::shared_ptr<const AbstractItemModel::AbstractItem>& itemTarget,
                             const char* source,
                             int32_t dropLocation)
{
}

std::string AbstractItemModel::getDragMimeData(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
    return {};
}

void AbstractItemModel::subscribe(ItemModelHelper* widget)
{
    m_widgets.insert(widget);
}

void AbstractItemModel::unsubscribe(ItemModelHelper* widget)
{
    m_widgets.erase(widget);
}

// Invoke the subscribed callbacks on a model and item. Note the item shared_ptr is held locally until all callbacks have completed.
template <typename T>
static void invokeCallbacks(AbstractItemModel& model, std::shared_ptr<const AbstractItemModel::AbstractItem> item, const T& callbacks)
{
    // Use a simpler index-based for-loop in case the underlying callbacks is re-allocated during the callback.
    // This relies on the fact that if removeXXXFn is called during callback, it will not shrink callback vector.
    // The current pattern also relies on a reference to the current callback rather than a copy/clone of the shared_ptr
    // because it is not used after callback returns.
    for (size_t i = 0, n = callbacks.size(); i < n; ++i)
    {
        if (auto&& callback = callbacks[i])
        {
            callback(&model, item.get());
        }
    }
}

uint32_t AbstractItemModel::addItemChangedFn(
    std::function<void(const AbstractItemModel*, const AbstractItemModel::AbstractItem*)> fn)
{
    uint32_t id = static_cast<uint32_t>(m_itemChangedCallbacks.size());
    m_itemChangedCallbacks.emplace_back(std::move(fn));
    return id;
}

void AbstractItemModel::removeItemChangedFn(uint32_t id)
{
    // We don't remove it to keep the ids that we already returned. Instead, we make this function NULL, so it will be
    // skipped.
    if (id < m_itemChangedCallbacks.size())
    {
        m_itemChangedCallbacks[id] = nullptr;
    }
    else
    {
        OMNIUI_LOG_ERROR("ItemChanged subscription was invalid");
    }
}

uint32_t AbstractItemModel::addBeginEditFn(
    std::function<void(const AbstractItemModel*, const AbstractItemModel::AbstractItem*)> fn)
{
    uint32_t id = static_cast<uint32_t>(m_beginEditCallbacks.size());
    m_beginEditCallbacks.emplace_back(std::move(fn));
    return id;
}

void AbstractItemModel::removeBeginEditFn(uint32_t id)
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

uint32_t AbstractItemModel::addEndEditFn(
    std::function<void(const AbstractItemModel*, const AbstractItemModel::AbstractItem*)> fn)
{
    uint32_t id = static_cast<uint32_t>(m_endEditCallbacks.size());
    m_endEditCallbacks.emplace_back(std::move(fn));
    return id;
}

void AbstractItemModel::removeEndEditFn(uint32_t id)
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

void AbstractItemModel::processBeginEditCallbacks(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;
    this->beginEdit(item);

    invokeCallbacks(*this, item, m_beginEditCallbacks);
}

void AbstractItemModel::processEndEditCallbacks(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    // XXX: AbstractValueModel::processEndEditCallbacks reverses this->endEdit and callback invocation order.
    this->endEdit(item);

    invokeCallbacks(*this, item, m_endEditCallbacks);
}

void AbstractItemModel::_itemChanged(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;
    // Notify everyone the value is changed
    for (auto widget : m_widgets)
    {
        widget->onModelUpdated(item);
    }

    invokeCallbacks(*this, item, m_itemChangedCallbacks);
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
