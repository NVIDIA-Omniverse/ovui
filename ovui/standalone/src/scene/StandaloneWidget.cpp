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

// Standalone stub for omni.ui.scene Widget.
//
// sc.Widget hosts a live omni.ui window rendered off-screen into a 3D scene
// rectangle. In standalone, Phase 1, this renders as a blank (transparent)
// rectangle — all other scene primitives (lines, curves, gestures, etc.) work
// fully.
//
// Phase 2 will replace this stub with an FBO-backed implementation that
// renders an omni::ui::Window into an OpenGL texture.
//

#include <omni/ui/scene/Widget.h>
#include <omni/ui/Frame.h>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

// Constructor: delegate to Rectangle with default (nullptr) RectangleData.
// No WidgetData is allocated since all Kit GPU/window logic is stubbed out.
Widget::Widget(Float width, Float height)
    : Rectangle(width, height)
{
}

// Destructor must be defined in exactly one translation unit so that the
// compiler emits the vtable and RTTI typeinfo here.  Because this file is
// compiled with OMNIUI_SCENE_EXPORTS (see standalone/CMakeLists.txt), the
// typeinfo is exported with default visibility and is reachable by pybind11.
Widget::~Widget() {}

// _preDrawContent: delegate to Rectangle base so geometry / gesture state is updated.
void Widget::_preDrawContent(
    const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height)
{
    Rectangle::_preDrawContent(input, projection, view, width, height);
}

// _rebuildCache: delegate to Rectangle; the UV subdivision done by Kit's
// Widget is omitted in standalone Phase 1 (no off-screen texture).
void Widget::_rebuildCache()
{
    Rectangle::_rebuildCache();
}

void Widget::_validateImageProvider()
{
    // No-op in standalone Phase 1: no off-screen window or GPU texture pipeline.
}

void Widget::_drawContent(const Matrix44& /*projection*/, const Matrix44& /*view*/)
{
    // No-op in standalone Phase 1: Widget renders as transparent/blank.
    // The rectangle geometry is still built by Rectangle::_drawContent in the
    // base class hierarchy — this override intentionally skips the texture path.
}

std::shared_ptr<omni::ui::Frame> Widget::getFrame()
{
    // No frame available in standalone Phase 1.
    return {};
}

void Widget::invalidate()
{
    // No-op: nothing to invalidate without an off-screen window.
}

float Widget::_computeResolutionWidth() const
{
    // Return the widget's geometry width, or minimum 32px.
    const float w = static_cast<float>(this->getWidth());
    return w > 0.0f ? w : 32.0f;
}

float Widget::_computeResolutionHeight() const
{
    // Return the widget's geometry height, or minimum 32px.
    const float h = static_cast<float>(this->getHeight());
    return h > 0.0f ? h : 32.0f;
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
