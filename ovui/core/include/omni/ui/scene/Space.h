/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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
