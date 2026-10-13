/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/scene/Space.h>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

const std::string& getSpaceName(Space space)
{
    static std::string spaces[] = { "current", "world", "object", "ndc", "screen" };
    static std::string unknown = "unknown";

    size_t spaceId = static_cast<size_t>(space);
    if (spaceId < sizeof(spaces) / sizeof(spaces[0]))
    {
        return spaces[spaceId];
    }

    return unknown;
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
