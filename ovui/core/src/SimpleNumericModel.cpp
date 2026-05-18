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

#include <omni/ui/SimpleNumericModel.h>
#include "platform/Log.h"

#include <algorithm>
#include <stdexcept>

OMNIUI_NAMESPACE_OPEN_SCOPE

std::string SimpleBoolModel::getValueAsString() const
{
    return this->getValue<bool>() ? "True" : "False";
}

void SimpleBoolModel::setValue(std::string value)
{
    static const std::vector<std::string> allFalses = { "False", "false", "0", "None" };
    this->_setNumericValue(!value.empty() && std::find(allFalses.begin(), allFalses.end(), value) == allFalses.end());
}

void SimpleFloatModel::setValue(std::string value)
{
    try
    {
        this->_setNumericValue(std::stof(value));
    }
    catch (const std::invalid_argument&)
    {
        // TODO: We need a way to tell that the model is currently invalid
        OMNIUI_LOG_WARN_ONCE("SimpleFloatModel float invalid_argument. Using 0.0");
        this->_setNumericValue(0.0f);
    }
    catch (const std::out_of_range&)
    {
        // TODO: We need a way to tell that the model is currently invalid
        OMNIUI_LOG_WARN_ONCE("SimpleFloatModel float out_of_range. Using 0.0");
        this->_setNumericValue(0.0f);
    }
}

void SimpleIntModel::setValue(std::string value)
{
    try
    {
        this->_setNumericValue(strtoll(value.c_str(), NULL, 10));
    }
    catch (const std::invalid_argument&)
    {
        // TODO: We need a way to tell that the model is currently invalid
        OMNIUI_LOG_WARN_ONCE("SimpleIntModel int invalid_argument. Using 0");
        this->_setNumericValue(0);
    }
    catch (const std::out_of_range&)
    {
        // TODO: We need a way to tell that the model is currently invalid
        OMNIUI_LOG_WARN_ONCE("SimpleIntModel int out_of_range. Using 0");
        this->_setNumericValue(0);
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
