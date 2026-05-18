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

#include <memory>

OMNIUI_NAMESPACE_OPEN_SCOPE

class FontAtlasTexture;
class Widget;
struct FontHelperPrivate;

/**
 * @brief The helper class for the widgets that are working with fonts.
 */
class OMNIUI_CLASS_API FontHelper
{
protected:
    OMNIUI_API
    FontHelper();

    OMNIUI_API
    virtual ~FontHelper();

    /**
     * @brief Push the font to the underlying windowing system if the font is available. It's in protected to make it
     * available to devired classes.
     */
    OMNIUI_API
    void _pushFont(const Widget& widget, bool overresolution = false);

    /**
     * @brief Push the font to the underlying windowing system if the font is available. It's in protected to make it
     * available to devired classes.
     */
    OMNIUI_API
    void _pushFont(float fontSize);

    /**
     * @brief Remove the font from the underlying windowing system if the font was pushed.
     */
    OMNIUI_API
    void _popFont() const;

    /**
     * @brief Checks the style, and save the font if necessary. We don't want this object to be derived from widget, so
     * we pass the widget as argument.
     *
     * @param widget the object we want to get the font style from.
     */
    void _updateFont(const Widget& widget, bool overresolution = false);

    /**
     * @brief Save the font if necessary.
     */
    void _updateFont(float fontSize, float scale, bool hasFontSizeStyle);

    /**
     * @brief Save the font if necessary.
     */
    void _updateFont(const char* font, float fontSize, float scale, bool hasFontSizeStyle, bool overresolution = false);

private:
    std::unique_ptr<FontHelperPrivate> m_prv;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
