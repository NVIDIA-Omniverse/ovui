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
#include "Window.h"

#include <memory>
#include <utility>
#include <string>

namespace omni
{
namespace kit
{
struct Window;
}
}

OMNIUI_NAMESPACE_OPEN_SCOPE


/**
 * @brief The ToolBar class represents a window in the underlying windowing system that as some fixed size property
 *
 */
class OMNIUI_CLASS_API ToolBar : public Window
{
public:
    enum class Axis : uint8_t
    {
        eX = 0,
        eY = 1,
        eNone = 2,
    };

    OMNIUI_API
    virtual ~ToolBar();

    // We need it to make sure it's created as a shared pointer.
    template <typename... Args>
    static std::shared_ptr<ToolBar> create(Args&&... args)
    {
        /* make_shared doesn't work because the constructor is protected: */
        /* auto ptr = std::make_shared<This>(std::forward<Args>(args)...); */
        /* TODO: Find the way to use make_shared */
        auto window = std::shared_ptr<ToolBar>{ new ToolBar{ std::forward<Args>(args)... } };
        Workspace::RegisterWindow(window);
        return window;
    }

    /**
     * @breif axis for the toolbar
     */
    OMNIUI_PROPERTY(ToolBar::Axis, axis, DEFAULT, Axis::eX, READ, getAxis, WRITE, setAxis, NOTIFY, setAxisChangedFn);

protected:
    struct ToolBarData;

    /**
     * @brief Construct ToolBar
     */
    OMNIUI_API
    ToolBar(const std::string& title);

    /**
     * @brief Execute the rendering code of the widget.
     *
     * It's in protected section because it can be executed only by this object itself.
     */
    virtual void _draw(const char* windowName, float elapsedTime) override;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
