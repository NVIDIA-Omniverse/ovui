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

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The Spacer class provides blank space.
 *
 * Normally, it's used to place other widgets correctly in a layout.
 *
 * TODO: Do we need to handle mouse events in this class?
 */
class OMNIUI_CLASS_API Spacer : public Widget
{
    OMNIUI_OBJECT(Spacer)

public:
    OMNIUI_API
    ~Spacer() override;

protected:
    /**
     * @brief Construct Spacer
     */
    OMNIUI_API
    Spacer();

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
