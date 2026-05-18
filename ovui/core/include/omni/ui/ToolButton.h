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

#include "Button.h"
#include "ValueModelHelper.h"

#include <memory>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief ToolButton is functionally similar to Button, but provides a model that determines if the button is checked.
 * This button toggles between checked (on) and unchecked (off) when the user clicks it.
 */
class OMNIUI_CLASS_API ToolButton : public Button, public ValueModelHelper
{
    OMNIUI_OBJECT(ToolButton)

public:
    OMNIUI_API
    ~ToolButton() override;

    /**
     * @brief Reimplemented from ValueModelHelper. It's called when the model is changed.
     */
    OMNIUI_API
    void onModelUpdated() override;

protected:
    /**
     * @brief Construct a checkable button with the model. If the bodel is not provided, then the default model is
     * created.
     *
     * @param model The model that determines if the button is checked.
     */
    OMNIUI_API
    ToolButton(const std::shared_ptr<AbstractValueModel>& model = {});

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

private:
    struct ToolButtonData;

    /**
     * @brief Reimplemented from InvisibleButton. Called then the user clicks this button. We don't use `m_clickedFn`
     * because the user can set it. If we are using it in our internal code and the user overrides it, the behavior of
     * the button will be changed.
     */
    OMNIUI_API
    void _clicked() override;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
