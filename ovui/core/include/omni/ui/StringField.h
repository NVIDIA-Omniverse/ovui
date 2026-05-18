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
 * @brief The StringField widget is a one-line text editor with a string model.
 */
class OMNIUI_CLASS_API StringField : public AbstractField
{
    OMNIUI_OBJECT(StringField)

public:
    /**
     * @brief This property holds the password mode. If the field is in the password mode when the entered text is obscured.
     */
    OMNIUI_PROPERTY(bool, passwordMode, DEFAULT, false, READ, isPasswordMode, WRITE, setPasswordMode);

    /**
     * @brief This property holds if the field is read-only.
     */
    OMNIUI_PROPERTY(bool, readOnly, DEFAULT, false, READ, isReadOnly, WRITE, setReadOnly);

    /**
     * @brief Multiline allows to press enter and create a new line.
     */
    OMNIUI_PROPERTY(bool, multiline, DEFAULT, false, READ, isMultiline, WRITE, setMultiline);

    /**
     * @brief This property holds if the field allows Tab input.
     */
    OMNIUI_PROPERTY(bool, allowTabInput, DEFAULT, false, READ, isTabInputAllowed, WRITE, setTabInputAllowed);

protected:
    struct StringFieldData;

    /**
     * @brief Constructs StringField
     *
     * @param model The widget's model. If the model is not assigned, the default model is created.
     */
    [[deprecated("Use StringField(std::shared_ptr<AbstractValueModel> model = {}, StringFieldData* data = nullptr) instead")]]
    OMNIUI_API
    StringField(const std::shared_ptr<AbstractValueModel>& model = {});

    /**
     * @brief Constructs StringField with custom private data provided by a subclass.
     */
    OMNIUI_API
    StringField(std::shared_ptr<AbstractValueModel> model, StringFieldData* data);

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
