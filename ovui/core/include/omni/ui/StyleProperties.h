/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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
