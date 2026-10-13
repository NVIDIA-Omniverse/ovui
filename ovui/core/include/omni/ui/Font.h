/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "Api.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief List of all font sizes
 */
enum class FontStyle
{
    eNone,

    /**
     * @brief 14
     */
    eNormal,

    /**
     * @brief 16
     */
    eLarge,

    /**
     * @brief 12
     */
    eSmall,

    /**
     * @brief 18
     */
    eExtraLarge,

    /**
     * @brief 20
     */
    eXXL,

    /**
     * @brief 22
     */
    eXXXL,

    /**
     * @brief 10
     */
    eExtraSmall,

    /**
     * @brief 8
     */
    eXXS,

    /**
     * @brief 6
     */
    eXXXS,

    /**
     * @brief 66
     */
    eUltra,

    eCount
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
