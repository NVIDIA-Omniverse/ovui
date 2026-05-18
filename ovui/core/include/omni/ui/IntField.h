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

#include "AbstractField.h"

#include <cstdint>
#include <memory>
#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The IntField widget is a one-line text editor with a string model.
 */
class OMNIUI_CLASS_API IntField : public AbstractField
{
    OMNIUI_OBJECT(IntField)

protected:
    /**
     * @brief Construct IntField
     */
    OMNIUI_API
    IntField(std::shared_ptr<AbstractValueModel> model = {});

private:
    /**
     * @brief It's necessary to implement it to convert model to string buffer that is displayed by the field. It's
     * possible to use it for setting the string format.
     */
    std::string _generateTextForField() override;

    /**
     * @brief Set/get the field data and the state on a very low level of the underlying system.
     */
    void _updateSystemText(void*) override;

    /**
     * @brief Determines the flags that are used in the underlying system widget.
     */
    int32_t _getSystemFlags() const override;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
