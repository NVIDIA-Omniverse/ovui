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

#include <memory>

OMNIUI_NAMESPACE_OPEN_SCOPE

class AbstractItemModel;

/**
 * @brief The ItemModelHelper class provides the basic functionality for item widget classes.
 *
 * TODO: It's very similar to ValueModelHelper. We need to template it. It's not templated now because we need a good
 * solution for pybind11. Pybind11 doesn't like templated classes.
 */
class OMNIUI_CLASS_API ItemModelHelper
{
public:
    OMNIUI_API
    virtual ~ItemModelHelper();

    /**
     * @brief Called by the model when the model value is changed. The class should react to the changes.
     *
     * @param item The item in the model that is changed. If it's NULL, the root is chaged.
     */
    OMNIUI_API
    virtual void onModelUpdated(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item) = 0;

    /**
     * @brief Set the current model.
     */
    OMNIUI_API
    virtual void setModel(std::shared_ptr<AbstractItemModel> model);

    /**
     * @brief Returns the current model.
     */
    OMNIUI_API
    virtual std::shared_ptr<AbstractItemModel> getModel() const;

protected:
    OMNIUI_API
    ItemModelHelper(std::shared_ptr<AbstractItemModel> model);

    template <typename T> inline T& _getModelData() const { return static_cast<T&>(*m_data); }

private:
    struct ItemModelHelperData;
    std::unique_ptr<ItemModelHelperData> m_data;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
