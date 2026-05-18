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

// Internal header: style-cascade -> RenderConfig resolver.  Extracted
// from MarkdownWidget so the heavy per-frame resolution can be cached
// behind a dirty flag.
//
#pragma once

#include "RenderConfig.h"

#include <omni/ui/FontAtlasTexture.h>
#include <omni/ui/StyleContainer.h>

#include <functional>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Per-widget font-face cache entry.
 *
 * The `probed` flag + `path` pair caches the result of the expensive
 * filesystem probe (`firstExistingPath`) so we don't hit the filesystem
 * every frame.  The entry is invalidated when the candidate list or
 * size changes (via the `fingerprint` string).
 */
struct MarkdownFontFaceCache
{
    std::string fingerprint; // candidate list + size hash
    std::string path;        // resolved path ("" means "probed, not found")
    bool probed = false;
    float size = 0.0f;
    std::shared_ptr<FontAtlasTexture> atlas;
};

struct MarkdownStyleCache
{
    std::unordered_map<std::string, MarkdownFontFaceCache> fontFaces;
};

/**
 * @brief Closure-based access to the widget's protected style machinery.
 *
 * The renderer cannot legally touch `Widget::_resolveStyleProperty` et
 * al. from a free function, so MarkdownWidget builds one of these to
 * bridge the gap.  All callbacks are invoked synchronously inside
 * `buildRenderConfig`; none are stored past the call.
 */
struct StyleAccessors
{
    std::function<bool(StyleColorProperty, uint32_t*)> resolveColor;
    std::function<bool(StyleFloatProperty, float*)> resolveFloat;
    std::function<bool(StyleStringProperty, const char**)> resolveString;

    std::function<bool(const char* group, StyleColorProperty, uint32_t*)> resolveGroupColor;
    std::function<bool(const char* group, StyleFloatProperty, float*)> resolveGroupFloat;
    std::function<bool(const char* group, StyleStringProperty, const char**)> resolveGroupString;

    // Push the widget's font into the ImGui stack and return the active
    // ImFont*.  Caller owns the matching pop.
    std::function<void()> pushFont;
};

/**
 * @brief Resolve the style cascade into a `RenderConfig`.
 *
 * Fills every field of `config` except the provider pointer and the
 * per-frame document generation (which the caller must set themselves
 * after buildRenderConfig returns, whether or not the cached result was
 * reused).
 *
 * Calls `accessors.pushFont` exactly once; the caller owns the matching
 * `_popFont` after rendering.
 */
void buildRenderConfig(const StyleAccessors& accessors, MarkdownStyleCache& cache, RenderConfig& config);

OMNIUI_NAMESPACE_CLOSE_SCOPE
