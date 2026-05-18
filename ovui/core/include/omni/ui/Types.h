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

#pragma once

#include "Api.h"

#include <cstdint>
#include <string>
#include <vector>

namespace omni {
namespace ui {

/// Keyboard modifier flags (bitmask).
using KeyboardModifierFlags = uint32_t;

constexpr KeyboardModifierFlags kKeyModShift = 1 << 0;   ///< Shift key.
constexpr KeyboardModifierFlags kKeyModCtrl  = 1 << 1;   ///< Control key.
constexpr KeyboardModifierFlags kKeyModAlt   = 1 << 2;   ///< Alt key.
constexpr KeyboardModifierFlags kKeyModSuper = 1 << 3;   ///< Super key.

/// Pixel format enum for image data.
enum class PixelFormat : uint32_t
{
    eUnknown = 0,
    eRGBA8_UNORM = 1,
    eRGBA8_SRGB = 2,
    eBGRA8_UNORM = 3,
    eR8_UNORM = 4,
    eRGBA16_FLOAT = 5,
    eRGBA32_FLOAT = 6,
    // Float AOV formats. Useful for visualising render-output buffers
    // (normals, world-space positions, depth) where the producer emits
    // raw float data the renderer wants to surface without quantising
    // to 8-bit.
    eR16_FLOAT = 7,
    eR32_FLOAT = 8,
    eRG16_FLOAT = 9,
    eRG32_FLOAT = 10,
    eRGB16_FLOAT = 11,
    eRGB32_FLOAT = 12,
};

/// 2-component unsigned integer vector.
struct UInt2
{
    uint32_t x = 0;
    uint32_t y = 0;
};

/// 2-component signed integer vector.
struct Int2
{
    int x = 0;
    int y = 0;
};

/// Opaque handle for an application window.
/// In Kit mode this wraps omni::kit::IAppWindow*; in standalone it wraps the
/// platform's own window pointer. Core code must never dereference it directly.
using AppWindowHandle = void*;

/// Display window rectangle in normalized coordinates.
struct DisplayWindowRect
{
    float x = 0.0f;
    float y = 0.0f;
    float z = 1.0f;  ///< right edge (normalized)
    float w = 1.0f;  ///< bottom edge (normalized)
};

enum class MarkdownAssetKind : uint8_t
{
    eRasterImage = 0,
    eSvgImage,
    eDiagramBlock,
    eMathInline,
    eMathBlock,
};

enum class MarkdownAssetState : uint8_t
{
    eUnsupported = 0,
    ePending,
    eReady,
    eFailed,
};

struct MarkdownAssetRequest
{
    MarkdownAssetKind kind = MarkdownAssetKind::eRasterImage;
    std::string source;
    std::string language;
    std::string altText;
    std::string title;
    float maxDisplayWidth = 0.0f;
    float fontSize = 14.0f;
    float deviceScale = 1.0f;
    bool inlineAsset = false;
    bool darkTheme = false;
    uint64_t styleHash = 0;
    uint64_t documentGeneration = 0;
};

struct MarkdownAssetResult
{
    MarkdownAssetState state = MarkdownAssetState::eUnsupported;

    // Texture handle path: provider owns the GPU resource, the widget just
    // binds it.  Prefer this when the provider already has a GPU-side image
    // (Kit ImageProvider, asset pipeline, etc).
    void* imGuiTextureId = nullptr;

    float width = 0.0f;
    float height = 0.0f;
    float uv0x = 0.0f;
    float uv0y = 0.0f;
    float uv1x = 1.0f;
    float uv1y = 1.0f;
    float baseline = 0.0f;
    std::string error;

    // Pixel bytes path: alternative to imGuiTextureId. When non-empty, the
    // widget uploads these through its normal image path and manages the GPU
    // texture. Providers that can't own GPU resources should prefer this.
    // This is the primary path for Python-side providers (pybind11 trampolines)
    // because Python code should never be responsible for GPU texture
    // lifetime.
    std::vector<uint8_t> pixels;         // tightly packed
    uint32_t pixelWidth = 0;
    uint32_t pixelHeight = 0;
    PixelFormat pixelFormat = PixelFormat::eRGBA8_UNORM;
};

/// Convenience factory: returns a result marked ePending (no data yet).
static inline MarkdownAssetResult pendingResult()
{
    MarkdownAssetResult r;
    r.state = MarkdownAssetState::ePending;
    return r;
}

/// Convenience factory: returns a result marked eUnsupported.
static inline MarkdownAssetResult unsupportedResult()
{
    MarkdownAssetResult r;
    r.state = MarkdownAssetState::eUnsupported;
    return r;
}

class OMNIUI_CLASS_API IMarkdownAssetProvider
{
public:
    virtual ~IMarkdownAssetProvider() = default;

    /**
     * @brief Request a provider-rendered Markdown asset.
     *
     * This method must not block on network, subprocess, JavaScript, SVG, or
     * math rendering work. Providers should return ePending while work is in
     * flight, then eReady/eFailed/eUnsupported on later calls for the same
     * stable request.
     *
     * Thread-safety: the widget currently only calls ``request`` from the
     * render thread, but provider implementations MUST treat this as
     * potentially called from any thread and take their own locks.  In
     * particular the future pybind11 binding will call into Python from the
     * render thread, and Python code must be prepared for GIL acquisition.
     */
    virtual MarkdownAssetResult request(const MarkdownAssetRequest& request) = 0;

    /**
     * @brief Optional per-frame pump for provider backends.
     *
     * Always called from the UI / render thread.  Use this to drain cross-
     * thread work queues, finalize GPU uploads, or advance async state.
     */
    virtual void tick()
    {
    }

    /**
     * @brief Optional cancellation hook when the widget reparses new text.
     *
     * The widget increments documentGeneration on every reparse.  When a
     * provider knows older generations are no longer needed it can cancel
     * their pending work to avoid wasting CPU on stale requests.
     */
    virtual void cancelGeneration(uint64_t generation)
    {
        (void)generation;
    }
};

} // namespace ui
} // namespace omni
