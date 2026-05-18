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

#include "AbstractItemModel.h"

#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

class SimpleStringModel;

/**
 * @brief A very simple model that holds the the root model and the flat list of models.
 */
class OMNIUI_CLASS_API SimpleListModel : public AbstractItemModel
{
public:
    static std::shared_ptr<SimpleListModel> create();

    template <typename T>
    static std::shared_ptr<SimpleListModel> create(const std::vector<T>& valueList, int32_t rootValue = 0);

    /**
     * @brief Reimplemented. Returns the vector of items that are nested to the given parent item.
     */
    OMNIUI_API
    std::vector<std::shared_ptr<const AbstractItem>> getItemChildren(
        const std::shared_ptr<const AbstractItem>& parentItem = nullptr) override;

    /**
     * @brief Reimplemented. Creates a new item from the value model and appends it to the list of the children of the
     * given item.
     */
    OMNIUI_API
    std::shared_ptr<const AbstractItem> appendChildItem(const std::shared_ptr<const AbstractItem>& parentItem,
                                                        std::shared_ptr<AbstractValueModel> model) override;

    /**
     * @brief Reimplemented. Removes the item from the model.
     */
    OMNIUI_API
    void removeItem(const std::shared_ptr<const AbstractItem>& item) override;

    OMNIUI_API
    size_t getItemValueModelCount(const std::shared_ptr<const AbstractItem>& item = nullptr) override;

    /**
     * @brief Reimplemented. Get the value model associated with this item.
     */
    OMNIUI_API
    std::shared_ptr<AbstractValueModel> getItemValueModel(const std::shared_ptr<const AbstractItem>& item = nullptr,
                                                          size_t index = 0) override;

protected:
    /**
     * @param rootModel The model that will be returned when querying the root item.
     * @param models The list of all the value submodels of this model.
     */
    OMNIUI_API
    SimpleListModel(std::shared_ptr<AbstractValueModel> rootModel,
                    const std::vector<std::shared_ptr<AbstractValueModel>>& models);

private:
    /**
     * @brief Storrage for the items.
     */
    class ListItem : public AbstractItemModel::AbstractItem
    {
    public:
        ListItem(const std::shared_ptr<AbstractValueModel>& model) : m_model{ model }, m_callbackId{ -1 }
        {
        }

        ~ListItem() override;

        // No copy
        ListItem(const ListItem&) = delete;
        // No copy-assignment
        ListItem& operator=(const ListItem&) = delete;
        // No move constructor and no move-assignments are allowed because of 12.8 [class.copy]/9 and 12.8
        // [class.copy]/20 of the C++ standard

        /**
         * @brief Keep callbackId from the model. When this object is destroyed, it removes this callback.
         *
         */
        void setCallbackId(int32_t callbackId);

    private:
        friend class SimpleListModel;
        std::shared_ptr<AbstractValueModel> m_model;
        int32_t m_callbackId;
    };

    std::shared_ptr<AbstractValueModel> m_rootModel;
    std::vector<std::shared_ptr<ListItem>> m_items;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
