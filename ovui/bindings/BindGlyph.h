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

#include <omni/ui/platform/PlatformRegistry.h>

#include <omni/ui/IGlyphManager.h>
#include <omni/ui/bind/BindUtils.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapGlyph(module& m)
{
    m.def("get_custom_glyph_code",
          [](const char* glyphFilePath, omni::ui::FontStyle fontStyle) {
              auto glyphManager = omni::ui::PlatformRegistry::instance().glyphManager();
              if (glyphManager)
              {
                  return glyphManager->getGlyphInfo(glyphFilePath, fontStyle).code;
              }
              return "?";
          },
          R"(
            Get glyph code.

            Args:
                file_path (str): Path to svg file
                font_style(:class:`.FontStyle`): font style to use.
            )",
          arg("file_path"), arg("font_style") = omni::ui::FontStyle::eNormal);
}
