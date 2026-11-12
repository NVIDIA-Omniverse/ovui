/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/Api.h>

#include <cstddef>

struct ImDrawData;

namespace omni
{
namespace ui
{

/**
 * @brief Removes the draw commands that use a presentation key that has no drawable.
 *
 * Call this once per frame, after ImGui::Render() and before the draw data goes to
 * a renderer back end. The renderer can retire a key after the widget asked for it, and a
 * client can draw a reference that it kept from an earlier frame. A key without a drawable must
 * never reach the back end: it would be read as a texture name, or as a descriptor index or pointer.
 *
 * Every key that getImGuiReference() gave out is checked in every later frame while a provider
 * holds it. When the last provider lets the key go (clear, byte upload, a new key, or destroy), the
 * feed is done: the key is checked in the pass of that frame and one more, then its records are
 * freed. This holds however many feeds end in one frame. A reference that a client keeps after that
 * is not checked, like a kept texture reference
 * of a destroyed provider. A command is kept only when the renderer reports its key as
 * mapped. A command whose texture id equals such a key is treated as that key.
 * The function writes one log line when it starts to remove the commands of a key, with the key
 * and the reason. It does not write a line for each frame.
 *
 * @return The number of draw commands that were removed.
 */
OMNIUI_API
size_t dropUnmappedPresentationKeys(ImDrawData* drawData);

} // namespace ui
} // namespace omni
