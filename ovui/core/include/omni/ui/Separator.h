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

#include "FontHelper.h"
#include "MenuItem.h"

#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The Separator class provides blank space.
 *
 * Normally, it's used to create separator line in the UI elements
 */
class OMNIUI_CLASS_API Separator : public MenuItem, public FontHelper
{
    OMNIUI_OBJECT(Separator)

public:
    OMNIUI_API
    ~Separator() override;


    /**
     * @brief It's called when the style is changed. It should be propagated to children to make the style cached and
     * available to children.
     */
    OMNIUI_API
    void cascadeStyle() override;

protected:
    /**
     * @brief Construct Separator
     */
    OMNIUI_API
    Separator(const std::string& text = "");

private:
    struct SeparatorData;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
