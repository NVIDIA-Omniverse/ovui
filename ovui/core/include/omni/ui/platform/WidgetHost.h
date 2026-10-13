/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "../Api.h"

#include <cstdint>
#include <memory>

OMNIUI_NAMESPACE_OPEN_SCOPE

class Frame;
class ImageProvider;
struct ImageProviderTextureOptions;

/**
 * @brief The host side of `omni.ui.scene.Widget`.
 *
 * A scene Widget shows omni.ui content drawn by the host into an image. The
 * host owns that window, its image and its input; the Widget in the scene
 * library asks the registered factory for one surface per Widget. Without a
 * registered factory a Widget draws nothing.
 */
class WidgetSurface
{
public:
    virtual ~WidgetSurface() = default;

    /// The root frame of the Widget's content, or nullptr.
    virtual std::shared_ptr<Frame> frame() const = 0;
    /// The image the content is drawn into.
    virtual ImageProvider* image() = 0;
    /// Called every drawn frame with the resolution of the Widget; `frozen`
    /// means the content need not be redrawn.
    virtual void update(float width, float height, bool frozen) = 0;
    /// Freezes or unfreezes redrawing of the content.
    virtual void setFrozen(bool frozen) = 0;
    /// True while the host window exists.
    virtual bool isValid() const = 0;
    /// Mouse moved to the normalised position (s, t); t = 0 is the top.
    virtual void mouseMove(float s, float t) = 0;
    /// Mouse button 0 (left), 1 (right) or 2 (middle) went down or up at (s, t).
    virtual void mouseButton(uint32_t button, bool pressed, float s, float t) = 0;
    /// Releases the host window. `final` is true when the Widget is destroyed.
    virtual void destroy(bool final) = 0;
};

/// Creates the surface of a Widget with the given resolution and texture options.
using WidgetSurfaceFactory = std::shared_ptr<WidgetSurface> (*)(float width,
                                                                float height,
                                                                const ImageProviderTextureOptions& textureOptions);

/// Registers the host's factory; nullptr removes it.
OMNIUI_API void setWidgetHost(WidgetSurfaceFactory factory);
/// The registered factory, or nullptr.
OMNIUI_API WidgetSurfaceFactory getWidgetHost();

OMNIUI_NAMESPACE_CLOSE_SCOPE
