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

#include <omni/ui/SimpleStringModel.h>
#include "platform/Log.h"
#include <stdexcept>

OMNIUI_NAMESPACE_OPEN_SCOPE

SimpleStringModel::SimpleStringModel(const std::string& defaultValue) : m_value{ defaultValue }
{
}

bool SimpleStringModel::getValueAsBool() const
{
    return !(m_value.empty() || m_value == "False");
}

double SimpleStringModel::getValueAsFloat() const
{
    try
    {
        return std::stof(m_value);
    }
    catch (const std::invalid_argument&)
    {
        OMNIUI_LOG_WARN_ONCE("SimpleStringModel float invalid_argument. Using 0.0");
        return 0.0;
    }
    catch (const std::out_of_range&)
    {
        OMNIUI_LOG_WARN_ONCE("SimpleStringModel float out_of_range. Using 0.0");
        return 0.0;
    }

}

int64_t SimpleStringModel::getValueAsInt() const
{
    try
    {
        return std::stoi(m_value);
    }
    catch (const std::invalid_argument&)
    {
        OMNIUI_LOG_WARN_ONCE("SimpleStringModel int invalid_argument. Using 0");
        return 0;
    }
    catch (const std::out_of_range&)
    {
        OMNIUI_LOG_WARN_ONCE("SimpleStringModel int out_of_range. Using 0");
        return 0;
    }
}

std::string SimpleStringModel::getValueAsString() const
{
    return m_value;
}

void SimpleStringModel::setValue(bool value)
{
    static const std::string trueStr = "True";
    static const std::string falseStr = "False";

    if (value)
    {
        this->setValue(trueStr);
    }
    else
    {
        this->setValue(falseStr);
    }
}

void SimpleStringModel::setValue(double value)
{
    this->setValue(std::to_string(value));
}

void SimpleStringModel::setValue(int64_t value)
{
    this->setValue(std::to_string(value));
}

void SimpleStringModel::setValue(std::string value)
{
    if (m_value != value)
    {
        m_value = std::move(value);
        this->_valueChanged();
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
