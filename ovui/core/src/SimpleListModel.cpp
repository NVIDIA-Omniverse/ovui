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

#include <omni/ui/SimpleListModel.h>
#include <omni/ui/SimpleNumericModel.h>
#include <omni/ui/SimpleStringModel.h>

#include <algorithm>
#include <iterator>

OMNIUI_NAMESPACE_OPEN_SCOPE

template <typename T>
std::shared_ptr<AbstractValueModel> createModelForType(const T& value);

template <>
std::shared_ptr<AbstractValueModel> createModelForType<bool>(const bool& value)
{
    return SimpleBoolModel::create(value);
}

template <>
std::shared_ptr<AbstractValueModel> createModelForType<float>(const float& value)
{
    return SimpleFloatModel::create(value);
}

template <>
std::shared_ptr<AbstractValueModel> createModelForType<double>(const double& value)
{
    return SimpleFloatModel::create(value);
}

template <>
std::shared_ptr<AbstractValueModel> createModelForType<int>(const int& value)
{
    return SimpleIntModel::create(value);
}

template <>
std::shared_ptr<AbstractValueModel> createModelForType<std::string>(const std::string& value)
{
    return SimpleStringModel::create(value);
}

std::shared_ptr<SimpleListModel> SimpleListModel::create()
{
    return std::shared_ptr<SimpleListModel>{ new SimpleListModel{ SimpleIntModel::create(), {} } };
}

template <typename T>
std::shared_ptr<SimpleListModel> SimpleListModel::create(const std::vector<T>& valueList, int32_t rootValue)
{
    // Create the value models for values.
    std::vector<std::shared_ptr<AbstractValueModel>> models;
    models.reserve(valueList.size());
    std::transform(valueList.begin(), valueList.end(), std::back_inserter(models),
                   [](const T& value) { return createModelForType(value); });

    // Create the object we need.
    return std::shared_ptr<SimpleListModel>{ new SimpleListModel{ SimpleIntModel::create(rootValue), models } };
}

SimpleListModel::SimpleListModel(std::shared_ptr<AbstractValueModel> rootModel,
                                 const std::vector<std::shared_ptr<AbstractValueModel>>& models)
    : m_rootModel{ std::move(rootModel) }
{
    // We don't keep callbackId because there is no way to replace root model.
    m_rootModel->addValueChangedFn(std::bind(&SimpleListModel::_itemChanged, this, nullptr));

    m_items.reserve(models.size());
    std::transform(models.begin(), models.end(), std::back_inserter(m_items),
                   [this](const std::shared_ptr<AbstractValueModel>& model)
                   {
                       auto item = std::make_shared<SimpleListModel::ListItem>(model);
                       uint32_t callbackId =
                           model->addValueChangedFn(std::bind(&SimpleListModel::_itemChanged, this, item));
                       item->setCallbackId(callbackId);
                       return item;
                   });
}

std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>> SimpleListModel::getItemChildren(
    const std::shared_ptr<const AbstractItemModel::AbstractItem>& parentItem)
{
    if (parentItem != nullptr)
    {
        // There is no support for nested items.
        return {};
    }

    std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>> result;
    // TODO: It's not correct because some items can be invalid. We need to count them first.
    result.reserve(m_items.size());

    for (const auto& item : m_items)
    {
        // Filter invalid items.
        if (item && item->m_model)
        {
            result.push_back(item);
        }
    }

    return result;
}

std::shared_ptr<const AbstractItemModel::AbstractItem> SimpleListModel::appendChildItem(
    const std::shared_ptr<const AbstractItemModel::AbstractItem>& parentItem, std::shared_ptr<AbstractValueModel> model)
{
    if (parentItem != nullptr)
    {
        // There is no support for nested items at the moment.
        return nullptr;
    }

    m_items.emplace_back(std::make_unique<ListItem>(model));
    auto& emplaced = m_items.back();
    uint32_t callbackId = model->addValueChangedFn(std::bind(&SimpleListModel::_itemChanged, this, emplaced));
    emplaced->setCallbackId(callbackId);

    this->_itemChanged(nullptr);
    return emplaced;
}

void SimpleListModel::removeItem(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
    // Find the item we are going to remove.
    auto found = std::find_if(
        m_items.begin(), m_items.end(), [item](const std::shared_ptr<ListItem>& i) { return i.get() == item.get(); });

    if (found != m_items.end())
    {
        m_items.erase(found);
        this->_itemChanged(nullptr);
    }
}

size_t SimpleListModel::getItemValueModelCount(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
    // TODO: Check if the item belongs to the current model.
    // This model has only one column.
    return 1;
}

std::shared_ptr<AbstractValueModel> SimpleListModel::getItemValueModel(
    const std::shared_ptr<const AbstractItemModel::AbstractItem>& item, size_t index)
{
    if (index != 0)
    {
        return {};
    }

    if (item == nullptr)
    {
        // Root
        return { m_rootModel };
    }

    // We need to make sure the item belongs to the current model, so we don't need to do dynamic_cast.
    auto found = std::find_if(
        m_items.begin(), m_items.end(), [item](const std::shared_ptr<ListItem>& i) { return i.get() == item.get(); });

    if (found != m_items.end())
    {
        return (*found)->m_model;
    }

    // Something went wrong
    return {};
}

SimpleListModel::ListItem::~ListItem()
{
    if (m_model && m_callbackId >= 0)
    {
        m_model->removeValueChangedFn(m_callbackId);
    }
}

void SimpleListModel::ListItem::setCallbackId(int32_t callbackId)
{
    m_callbackId = callbackId;
}

template OMNIUI_API std::shared_ptr<SimpleListModel> SimpleListModel::create<bool>(const std::vector<bool>& valueList,
                                                                                   int32_t rootValue);
template OMNIUI_API std::shared_ptr<SimpleListModel> SimpleListModel::create<float>(const std::vector<float>& valueList,
                                                                                    int32_t rootValue);
template OMNIUI_API std::shared_ptr<SimpleListModel> SimpleListModel::create<double>(const std::vector<double>& valueList,
                                                                                     int32_t rootValue);
template OMNIUI_API std::shared_ptr<SimpleListModel> SimpleListModel::create<int32_t>(const std::vector<int32_t>& valueList,
                                                                                      int32_t rootValue);
template OMNIUI_API std::shared_ptr<SimpleListModel> SimpleListModel::create<std::string>(
    const std::vector<std::string>& valueList, int32_t rootValue);

OMNIUI_NAMESPACE_CLOSE_SCOPE
