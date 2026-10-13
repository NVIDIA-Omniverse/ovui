/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "Button.h"

#include <memory>

OMNIUI_NAMESPACE_OPEN_SCOPE

class RadioCollection;

/**
 * @brief RadioButton is the widget that allows the user to choose only one of a predefined set of mutually exclusive
 * options.
 *
 * RadioButtons are arranged in collections of two or more with the class RadioCollection, which is the central
 * component of the system and controls the behavior of all the RadioButtons in the collection.
 *
 * @see RadioCollection
 */
class OMNIUI_CLASS_API RadioButton : public Button
{
    OMNIUI_OBJECT(RadioButton)

public:
    OMNIUI_API
    ~RadioButton() override;

    /**
     * @brief This property holds the button's text.
     */
    OMNIUI_PROPERTY(std::shared_ptr<RadioCollection>,
                    radioCollection,
                    READ,
                    getRadioCollection,
                    WRITE,
                    setRadioCollection,
                    NOTIFY,
                    onRadioCollectionChangedFn);

protected:
    /**
     * @brief Constructs RadioButton
     */
    OMNIUI_API
    RadioButton();

private:
    /**
     * @brief Reimplemented from InvisibleButton. Called then the user clicks this button. We don't use `m_clickedFn`
     * because the user can set it. If we are using it in our internal code and the user overrides it, the behavior of
     * the button will be changed.
     */
    OMNIUI_API
    void _clicked() override;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
