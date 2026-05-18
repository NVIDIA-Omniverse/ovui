/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
#include "StyleContainer.h"

#include <memory>


OMNIUI_NAMESPACE_OPEN_SCOPE

class Container;

/**
 * @brief A singleton that controls the global style of the session.
 */
class OMNIUI_CLASS_API Style
{
public:
    /**
     * @brief Get the instance of this singleton object.
     */
    OMNIUI_API
    static Style& getInstance();

    OMNIUI_API
    virtual ~Style();

    // A singletom pattern
    Style(Style const&) = delete;
    void operator=(Style const&) = delete;

    /**
     * @brief Returns the default root style. It's the style that is preselected when no alternative is specified.
     */
    OMNIUI_API
    std::shared_ptr<StyleContainer> const& getDefaultStyle() const;

    /**
     * @brief Set the default root style. It's the style that is preselected when no alternative is specified.
     */
    OMNIUI_API
    void setDefaultStyle(std::shared_ptr<StyleContainer> const& v);

    /**
     * @brief Set the default root style. It's the style that is preselected when no alternative is specified.
     */
    OMNIUI_API
    void setDefaultStyle(StyleContainer&& style);

    /**
     * @brief Connect the widget to the default root style.
     */
    void connectToGlobalStyle(const std::shared_ptr<Widget>& widget);

private:
    Style();

    std::shared_ptr<Container> m_rootStyleWidget;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
