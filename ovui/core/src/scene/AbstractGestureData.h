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
#include <omni/ui/scene/AbstractGesture.h>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct AbstractGesture::AbstractGestureData
{
    virtual ~AbstractGestureData();

    std::shared_ptr<GestureManager> m_manager = nullptr;

    GestureState m_previousState = GestureState::eNone;
    GestureState m_state = GestureState::eNone;
    bool m_stateChanged = false;
    bool m_cachedCanBePrevented = false;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
