/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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
