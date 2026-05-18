/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include <string>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief 3D positions and transformations exist within coordinate systems
 * called spaces.
 */
enum class Space
{
    eCurrent = 0,
    eWorld,
    eObject,
    eNdc,
    eScreen,
};

/**
 * @brief Get the string with the name of the given space
 */
const std::string& getSpaceName(Space space);

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
