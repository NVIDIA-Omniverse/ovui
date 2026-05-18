/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#include "StandaloneGlyphManager.h"

#include <imgui/imgui.h>

namespace omni {
namespace ui {
namespace standalone {

// Map FontStyle → pixel size (matches FontHelper.cpp thresholds)
static const struct { FontStyle style; float size; } kSizeTable[] = {
    { FontStyle::eXXXS,       6.0f  },
    { FontStyle::eXXS,        8.0f  },
    { FontStyle::eExtraSmall, 10.0f },
    { FontStyle::eSmall,      12.0f },
    { FontStyle::eNormal,     14.0f },
    { FontStyle::eLarge,      16.0f },
    { FontStyle::eExtraLarge, 18.0f },
    { FontStyle::eXXL,        20.0f },
    { FontStyle::eXXXL,       22.0f },
    // eUltra is the overresolution bucket used for any font_size > 23.
    // FontHelper scales it down to the requested size, so loading at 100 px
    // gives sharp results across a wide range (24 – 100 px).
    { FontStyle::eUltra,     100.0f },
};

bool StandaloneGlyphManager::loadFonts(const std::string& fontPath, float dpiScale)
{
    if (fontPath.empty())
        return false;

    ImGuiIO& io = ImGui::GetIO();
    bool any = false;

    for (auto& entry : kSizeTable)
    {
        float px = entry.size * dpiScale;
        ImFont* font = io.Fonts->AddFontFromFileTTF(fontPath.c_str(), px);
        if (font)
        {
            m_fonts[static_cast<int>(entry.style)] = font;
            any = true;
        }
    }

    return any;
}

void* StandaloneGlyphManager::getFont(FontStyle style)
{
    auto it = m_fonts.find(static_cast<int>(style));
    return (it != m_fonts.end()) ? it->second : nullptr;
}

} // namespace standalone
} // namespace ui
} // namespace omni
