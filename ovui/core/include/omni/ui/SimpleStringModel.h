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

#include "AbstractValueModel.h"

#include <cstdint>
#include <memory>
#include <string>
#include <utility>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief A very simple value model that holds a single string.
 */
class OMNIUI_CLASS_API SimpleStringModel : public AbstractValueModel
{
public:
    using Base = SimpleStringModel;
    using CarriedType = std::string;

    template <typename... Args>
    static std::shared_ptr<SimpleStringModel> create(Args&&... args)
    {
        /* make_shared doesn't work because the constructor is protected: */
        /* auto ptr = std::make_shared<This>(std::forward<Args>(args)...); */
        /* TODO: Find the way to use make_shared */
        return std::shared_ptr<SimpleStringModel>{ new SimpleStringModel{ std::forward<Args>(args)... } };
    }

    /**
     * @brief Get the value.
     */
    OMNIUI_API
    bool getValueAsBool() const override;
    OMNIUI_API
    double getValueAsFloat() const override;
    OMNIUI_API
    int64_t getValueAsInt() const override;
    OMNIUI_API
    std::string getValueAsString() const override;

    /**
     * @brief Set the value.
     */
    OMNIUI_API
    void setValue(bool value) override;
    OMNIUI_API
    void setValue(double value) override;
    OMNIUI_API
    void setValue(int64_t value) override;
    OMNIUI_API
    void setValue(std::string value) override;

protected:
    OMNIUI_API
    SimpleStringModel(const std::string& defaultValue = {});

private:
    std::string m_value;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
