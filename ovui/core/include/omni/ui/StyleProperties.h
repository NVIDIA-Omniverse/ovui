/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

OMNIUI_NAMESPACE_OPEN_SCOPE

enum class StyleFloatProperty
{
    eBorderRadius = 0,
    eBorderWidth,
    eFontSize,
    eMargin,
    eMarginWidth,
    eMarginHeight,
    ePadding,
    eScrollbarSize,
    ePaddingWidth,
    ePaddingHeight,
    eSecondaryPadding,
    eShadowThickness,
    eShadowOffsetX,
    eShadowOffsetY,
    eCount
};

enum class StyleEnumProperty
{
    eCornerFlag = 0,
    eAlignment,
    eFillPolicy,
    eDrawMode,
    eStackDirection,
    eShadowFlag,
    eCount
};

enum class StyleColorProperty
{
    eBackgroundColor = 0,
    eBackgroundGradientColor,
    eBackgroundSelectedColor,
    eBorderColor,
    eColor,
    eSelectedColor,
    eSecondaryColor,
    eSecondarySelectedColor,
    eSecondaryBackgroundColor,
    eDebugColor,
    eShadowColor,
    eCount
};

enum class StyleStringProperty
{
    eImageUrl = 0,
    eFont,
    eLayoutPolicy,
    eCount
};


OMNIUI_NAMESPACE_CLOSE_SCOPE
