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

#include "WidgetData.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

struct Button::ButtonData : public Widget::WidgetData
{
    ~ButtonData() override;

    // The background rectangle of the button for fast access.
    std::shared_ptr<Rectangle> m_rectangleWidget;
    // The main layout. All the sub-widgets (Label and Rectangle) are children of the main layout.
    std::shared_ptr<Stack> m_labelImageLayout;
    // The text of the button for fast access.
    std::shared_ptr<Label> m_labelWidget;
    std::shared_ptr<Image> m_imageWidget;

    // Flag that the content size is computed. We need it because we don't want to recompute the size each call of
    // draw().
    float m_minimalContentWidth = 0.f;
    float m_minimalContentHeight = 0.f;

    // Flag when the image visibility can potentially be changed
    bool m_imageVisibilityUpdated = false;
    bool m_minimalContentSizeComputed = false;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
