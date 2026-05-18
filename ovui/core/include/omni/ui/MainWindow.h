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

#include "Api.h"
#include "Property.h"

#include <memory>
#include <utility>

OMNIUI_NAMESPACE_OPEN_SCOPE

namespace windowmanager
{
class IWindowCallback;
}

class MenuBar;
struct MainWindowPrivate;

/**
 * @brief The MainWindow class represents Main Window for the Application, draw optional MainMenuBar and StatusBar
 *
 */
class OMNIUI_CLASS_API MainWindow : public std::enable_shared_from_this<MainWindow>, protected CallbackHelper<MainWindow>
{
public:
    virtual ~MainWindow();

    /**
     * @brief Removes all the callbacks and circular references.
     */
    OMNIUI_API
    virtual void destroy();

    // We need it to make sure it's created as a shared pointer.
    template <typename... Args>
    static std::shared_ptr<MainWindow> create(Args&&... args)
    {
        /* make_shared doesn't work because the constructor is protected: */
        /* auto ptr = std::make_shared<This>(std::forward<Args>(args)...); */
        /* TODO: Find the way to use make_shared */
        auto window = std::shared_ptr<MainWindow>{ new MainWindow{ std::forward<Args>(args)... } };
        return window;
    }

    /**
     * @brief The main MenuBar for the application
     */
    OMNIUI_PROPERTY(std::shared_ptr<MenuBar>, mainMenuBar, READ, getMainMenuBar, PROTECTED, WRITE, setMainMenuBar);

    /**
     * @brief This represents Styling opportunity for the Window background
     */
    OMNIUI_PROPERTY(std::shared_ptr<Frame>, mainFrame, READ, getMainFrame, PROTECTED, WRITE, setMainFrame);

    /**
     * @brief The StatusBar Frame is empty by default and is meant to be filled by other part of the system
     */
    OMNIUI_PROPERTY(std::shared_ptr<Frame>, statusBarFrame, READ, getStatusBarFrame, PROTECTED, WRITE, setStatusBarFrame);

    /**
     * @brief Workaround to reserve space for C++ status bar
     */
    OMNIUI_PROPERTY(bool, cppStatusBarEnabled, DEFAULT, false, READ, getCppStatusBarEnabled, WRITE, setCppStatusBarEnabled);

    /**
     * @brief When show_foreground is True, MainWindow prevents other windows from showing.
     */
    OMNIUI_PROPERTY(bool,
                    showForeground,
                    DEFAULT,
                    false,
                    READ,
                    isShowForeground,
                    WRITE,
                    setShowForeground,
                    PROTECTED,
                    NOTIFY,
                    _setShowForegroundChangedFn);

    /**
     * @brief Set the enabvled state of the Window
     */
    OMNIUI_API
    void setActive(bool active, bool showForeground = true);

protected:
    /**
     * @brief Construct the main window, add it to the underlying windowing system, and makes it appear.
     */
    OMNIUI_API
    MainWindow(bool showForeground = false);

    /**
     * @brief Execute the rendering code of the widget.
     *
     * It's in protected section because it can be executed only by this object itself.
     */
    virtual void _draw(float elapsedTime);

    /**
     * @brief Execute the rendering code that prevents other windows from showing.
     */
    virtual void _drawForeground(float elapsedTime);

private:
    // Private implementation (CachedBoolSetting etc.) hidden behind pimpl.
    std::unique_ptr<MainWindowPrivate> m_prv;

    float m_viewportSizeX = 0.0f;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
