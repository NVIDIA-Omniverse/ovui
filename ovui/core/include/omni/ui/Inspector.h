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

#include <cstdint>
#include <memory>
#include <string>
#include <utility>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Inspector is the helper to check the internal state of the widget.
 * It's not recommended to use it for the routine UI.
 */
class OMNIUI_CLASS_API Inspector
{
public:
    /**
     * @brief Get the children of the given Widget.
     */
    OMNIUI_API
    static std::vector<std::shared_ptr<Widget>> getChildren(const std::shared_ptr<Widget>& widget);

    /**
     * @brief Get the resolved style of the given Widget.
     */
    OMNIUI_API
    static const std::shared_ptr<StyleContainer>& getResolvedStyle(const std::shared_ptr<Widget>& widget);

    /**
     * @brief Start counting how many times Widget::setComputedWidth is called
     */
    OMNIUI_API
    static void beginComputedWidthMetric();

    /**
     * @brief Increases the number Widget::setComputedWidth is called
     */
    OMNIUI_API
    static void bumpComputedWidthMetric();

    /**
     * @brief Start counting how many times Widget::setComputedWidth is called
     * and return the number
     */
    OMNIUI_API
    static size_t endComputedWidthMetric();

    /**
     * @brief Start counting how many times Widget::setComputedHeight is called
     */
    OMNIUI_API
    static void beginComputedHeightMetric();

    /**
     * @brief Increases the number Widget::setComputedHeight is called
     */
    OMNIUI_API
    static void bumpComputedHeightMetric();

    /**
     * @brief Start counting how many times Widget::setComputedHeight is called
     * and return the number
     */
    OMNIUI_API
    static size_t endComputedHeightMetric();

    /**
     * @brief Provides the information about font atlases
     */
    OMNIUI_API
    static std::vector<std::pair<std::string, uint32_t>> getStoredFontAtlases();
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
