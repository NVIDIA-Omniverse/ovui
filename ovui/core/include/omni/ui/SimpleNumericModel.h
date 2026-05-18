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
#include "Property.h"

#include <cstdint>
#include <algorithm>
#include <memory>
#include <string>
#include <utility>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief A very simple value model that holds a single number. It's still an abstract class. It's necessary to
 * reimplement `setValue(std::string value)` because each numeric type can be represented with different string.
 */
template <typename T>
class OMNIUI_CLASS_API SimpleNumericModel : public AbstractValueModel
{
public:
    using Base = SimpleNumericModel<T>;
    using CarriedType = T;

    /**
     * @brief This property holds the model's minimum value.
     */
    OMNIUI_PROPERTY(T, min, DEFAULT, T(1), READ_VALUE, getMin, WRITE, setMin);

    /**
     * @brief This property holds the model's maximum value.
     */
    OMNIUI_PROPERTY(T, max, DEFAULT, T(0), READ_VALUE, getMax, WRITE, setMax);

    /**
     * @brief Get the value as bool.
     */
    bool getValueAsBool() const override
    {
        return m_value != static_cast<T>(0);
    }

    /**
     * @brief Get the value as double.
     */
    double getValueAsFloat() const override
    {
        return static_cast<double>(m_value);
    }

    /**
     * @brief Get the value as int64_t.
     */
    int64_t getValueAsInt() const override
    {
        return static_cast<int64_t>(m_value);
    }

    /**
     * @brief Get the value as string.
     */
    std::string getValueAsString() const override
    {
        return std::to_string(m_value);
    }

    /**
     * @brief Set the bool value. It will convert bool to the model's typle.
     */
    void setValue(bool value) override
    {
        this->_setNumericValue(static_cast<T>(value));
    }

    /**
     * @brief Set the double value. It will convert double to the model's typle.
     */
    void setValue(double value) override
    {
        this->_setNumericValue(static_cast<T>(value));
    }

    /**
     * @brief Set the int64_t value. It will convert int64_t to the model's typle.
     */
    void setValue(int64_t value) override
    {
        this->_setNumericValue(static_cast<T>(value));
    }

protected:
    SimpleNumericModel(T defaultValue = static_cast<T>(0)) : m_value{ defaultValue }
    {
    }

    /**
     * @brief Template to set the value of native type.
     */
    void _setNumericValue(T value)
    {
        // Clamp
        if (this->getMin() <= this->getMax())
        {
            value = std::min(this->getMax(), std::max(this->getMin(), value));
        }

        if (m_value != value)
        {
            m_value = value;
            this->_valueChanged();
        }
    }

private:
    T m_value;
};

#define SIMPLENUMERICMODEL_CREATOR(THIS)                                                                               \
public:                                                                                                                \
    using This = THIS;                                                                                                 \
    template <typename... Args>                                                                                        \
    static std::shared_ptr<This> create(Args&&... args)                                                                \
    {                                                                                                                  \
        return std::shared_ptr<This>{ new This{ std::forward<Args>(args)... } };                                       \
    }                                                                                                                  \
                                                                                                                       \
protected:                                                                                                             \
    THIS(CarriedType devaultValue = {}) : SimpleNumericModel<CarriedType>{ devaultValue }                              \
    {                                                                                                                  \
    }

/**
 * @brief A very simple bool model.
 */
class OMNIUI_CLASS_API SimpleBoolModel : public SimpleNumericModel<bool>
{
    SIMPLENUMERICMODEL_CREATOR(SimpleBoolModel)

public:
    OMNIUI_API
    std::string getValueAsString() const override;

    // Reimplemented because it's a special case for string.
    OMNIUI_API
    void setValue(std::string value) override;
};

/**
 * @brief A very simple double model.
 */
class OMNIUI_CLASS_API SimpleFloatModel : public SimpleNumericModel<double>
{
    SIMPLENUMERICMODEL_CREATOR(SimpleFloatModel)

public:
    // Reimplemented because it's a special case for string.
    OMNIUI_API
    void setValue(std::string value) override;
};

/**
 * @brief A very simple Int model.
 */
class OMNIUI_CLASS_API SimpleIntModel : public SimpleNumericModel<int64_t>
{
    SIMPLENUMERICMODEL_CREATOR(SimpleIntModel)

public:
    // Reimplemented because it's a special case for string.
    OMNIUI_API
    void setValue(std::string value) override;
};

#undef SIMPLENUMERICMODEL_CREATOR

OMNIUI_NAMESPACE_CLOSE_SCOPE
