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

#pragma once

#include <omni/ui/scene/ClickGesture.h>

#include "ShapeGestureData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct ClickGesture::ClickGestureData : public ShapeGesture::ShapeGestureData
{
    ~ClickGestureData() override = default;

    Vector3 m_itemLastPoint = Vector3{ 0.0 };
    Vector3 m_rayLastPoint = Vector3{ 0.0 };

    // We need it because the gesture is triggered with a delay.
    std::chrono::steady_clock::time_point m_startedAt;

    // Flag that indicates the state when the gesture is about to ended.
    bool m_readyForEnd = false;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
