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

OMNIUI_NAMESPACE_OPEN_SCOPE

class AbstractItemModel;

/**
 * @brief AbstractItemDelegate is used to generate widgets that display and edit data items from a model.
 */
class OMNIUI_CLASS_API AbstractItemDelegate
{
public:
    OMNIUI_API
    virtual ~AbstractItemDelegate();

    /**
     * @brief This pure abstract method must be reimplemented to generate custom collapse/expand button.
     */
    OMNIUI_API
    virtual void buildBranch(const std::shared_ptr<AbstractItemModel>& model,
                             const std::shared_ptr<const AbstractItemModel::AbstractItem>& item = nullptr,
                             size_t index = 0,
                             uint32_t level = 0,
                             bool expanded = false);

    /**
     * @brief This pure abstract method must be reimplemented to generate custom widgets for specific item in the model.
     */
    virtual void buildWidget(const std::shared_ptr<AbstractItemModel>& model,
                             const std::shared_ptr<const AbstractItemModel::AbstractItem>& item = nullptr,
                             size_t index = 0,
                             uint32_t level = 0,
                             bool expanded = false) = 0;

    /**
     * @brief This pure abstract method must be reimplemented to generate custom widgets for the header table.
     */
    OMNIUI_API
    virtual void buildHeader(size_t index = 0);

protected:
    /**
     * @brief Constructs AbstractItemDelegate
     */
    OMNIUI_API
    AbstractItemDelegate();
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
