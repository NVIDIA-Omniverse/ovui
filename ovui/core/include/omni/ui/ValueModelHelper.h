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

#include "Widget.h"

#include <cstdint>
#include <memory>

OMNIUI_NAMESPACE_OPEN_SCOPE

class AbstractValueModel;

/**
 * @brief The ValueModelHelper class provides the basic functionality for value widget classes.
 *
 * ValueModelHelper class is the base class for every standard widget that uses a AbstractValueModel.
 * ValueModelHelper is an abstract class and itself cannot be instantiated. It provides a standard interface for
 * interoperating with models.
 */
class OMNIUI_CLASS_API ValueModelHelper
{
public:
    OMNIUI_API
    virtual ~ValueModelHelper();

    /**
     * @brief Called by the model when the model value is changed. The class should react to the changes.
     */
    OMNIUI_API
    virtual void onModelUpdated() = 0;

    /**
     * @brief Set the current model.
     */
    OMNIUI_API
    virtual void setModel(std::shared_ptr<AbstractValueModel> model);

    /**
     * @brief Returns the current model.
     */
    OMNIUI_API
    virtual std::shared_ptr<AbstractValueModel> getModel() const;

protected:
    struct ValueModelHelperData;
    friend class RadioCollection;

    OMNIUI_API
    ValueModelHelper(std::shared_ptr<AbstractValueModel> model);

    OMNIUI_API
    ValueModelHelper(ValueModelHelperData* data = nullptr);

    template <typename T> inline T& _getModelData() const { return static_cast<T&>(*m_data); }

private:
    std::unique_ptr<ValueModelHelperData> m_data;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
