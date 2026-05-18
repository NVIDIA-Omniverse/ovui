/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
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
