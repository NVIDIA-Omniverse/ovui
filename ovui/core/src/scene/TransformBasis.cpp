/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/scene/TransformBasis.h>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

TransformBasis::~TransformBasis()
{
}

Matrix44 TransformBasis::convertFromWorld(const Matrix44& other)
{
    const auto myInverse = getMatrix().getInverse();
    return myInverse * other;
}

void TransformBasis::_attachToTransform()
{
}

void TransformBasis::_detachFromTransform()
{
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
