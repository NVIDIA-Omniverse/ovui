/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "Menu.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The MenuBar class provides a MenuBar at the top of the Window, could also be the MainMenuBar of the MainWindow
 *
 * it can only contain Menu, at the moment there is no way to remove item appart from clearing it all together
 */
class OMNIUI_CLASS_API MenuBar : public Menu
{
    OMNIUI_OBJECT(MenuBar)

public:
    OMNIUI_API
    ~MenuBar() override;

protected:
    /**
     * @brief Construct MenuBar
     */
    OMNIUI_API
    MenuBar(bool mainMenuBar = false);

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * Draw the content.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

private:
    struct MenuBarData;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
