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

#include <omni/ui/Frame.h>
#include <omni/ui/windowmanager/IWindowCallbackManager.h>

#include <memory>
#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

namespace windowmanager
{
struct WindowSet;
}

class MenuBar;

/**
 * @brief The DockSpace class represents Dock Space for the OS Window
 *
 */
class OMNIUI_CLASS_API DockSpace
{
public:
    virtual ~DockSpace();

    // We need it to make sure it's created as a shared pointer.
    template <typename... Args>
    static std::shared_ptr<DockSpace> create(Args&&... args)
    {
        /* make_shared doesn't work because the constructor is protected: */
        /* auto ptr = std::make_shared<This>(std::forward<Args>(args)...); */
        /* TODO: Find the way to use make_shared */
        auto dockSpace = std::shared_ptr<DockSpace>{ new DockSpace{ std::forward<Args>(args)... } };
        return dockSpace;
    }

    /**
     * @brief This represents Styling opportunity for the Window background
     */
    OMNIUI_PROPERTY(std::shared_ptr<Frame>, dockFrame, READ, getDockFrame, PROTECTED, WRITE, setDockFrame);

protected:
    /**
     * @brief Construct the main window, add it to the underlying windowing system, and makes it appear.
     */
    OMNIUI_API
    DockSpace(windowmanager::WindowSet* windowSet = nullptr);

    /**
     * @brief Execute the rendering code of the widget.
     *
     * It's in protected section because it can be executed only by this object itself.
     */
    virtual void _draw(float elapsedTime);

private:
    // the windowCallback
    windowmanager::IWindowCallbackPtr m_windowCallback;
    windowmanager::WindowSet* m_windowSet = nullptr;
    std::string m_name;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
