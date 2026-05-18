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

#include <functional>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The InvisibleButton widget provides a transparent command button.
 */
class OMNIUI_CLASS_API InvisibleButton : public Widget
{
    OMNIUI_OBJECT(InvisibleButton)

public:
    OMNIUI_API
    ~InvisibleButton() override;

    /**
     * @brief Sets the function that will be called when when the button is activated (i.e., pressed down then released
     * while the mouse cursor is inside the button).
     */
    OMNIUI_CALLBACK(Clicked, void);

protected:
    /**
     * Constructor.
     */
    OMNIUI_API
    InvisibleButton(WidgetData* data = nullptr);

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

private:
    /**
     * @brief Called then the user clicks this button.
     */
    OMNIUI_API
    virtual void _clicked();
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
