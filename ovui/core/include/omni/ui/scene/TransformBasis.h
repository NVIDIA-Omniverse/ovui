/*
 * SPDX-FileCopyrightText: Copyright (c) 2023-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include "Math.h"

#include <memory>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief A basis for mutating the transform space of a omni::ui::scene::Transform object.
 *
 * This class can be subclassed to implement custom space transformations. Transform objects containing
 * a TransformBasis will base their transform off of the space described therein.
 */
class OMNIUI_SCENE_CLASS_API TransformBasis : public std::enable_shared_from_this<TransformBasis>
{
public:
    OMNIUI_SCENE_API
    virtual ~TransformBasis();

    /**
     * @brief Given a world-space transform matrix, return a matrix describing the transform from the supplied
     * matrix into the space described by this basis object.
     *
     * @param other The world-space transform to convert
     * @return Matrix44 A transform representing the supplied matrix in the space described by this basis object
     */
    OMNIUI_SCENE_API
    Matrix44 convertFromWorld(const Matrix44& other);

    /**
     * @brief Get a world-space matrix describing the origin point of the space described
     *
     * @return Matrix44 the transformation matrix needed to convert to the described space's coordinates
     */
    OMNIUI_SCENE_API
    virtual Matrix44 getMatrix() = 0;

protected:
    friend class Transform;

    /**
     * @brief Reimplement if your TransformBasis subclass needs to know when it's been attached to a transform
     *
     */
    OMNIUI_SCENE_API
    virtual void _attachToTransform();

    /**
     * @brief Reimplement if your TransformBasis subclass needs to know when it's been detached from a transform
     *
     */
    OMNIUI_SCENE_API
    virtual void _detachFromTransform();
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
