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

#include "AbstractContainer.h"
#include "Math.h"
#include "Object.h"
#include "Space.h"
#include "TransformBasis.h"

#include <memory>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief Transforms children with component affine transformations
 */
class OMNIUI_SCENE_CLASS_API Transform : public AbstractContainer
{
    OMNIUI_SCENE_OBJECT(Transform);

public:
    enum class LookAt
    {
        eNone = 0,
        eCamera,
    };

    OMNIUI_SCENE_API
    virtual ~Transform();

    OMNIUI_SCENE_API
    virtual void destroy();

    Matrix44 getAccumulatedTransform() const override;

    /**
     * @brief Single transformation matrix
     */
    OMNIUI_PROPERTY(Matrix44,
                    transform,
                    DEFAULT,
                    Matrix44{ (Float)1.0 },
                    READ,
                    getTransform,
                    WRITE,
                    setTransform,
                    PROTECTED,
                    NOTIFY,
                    _setTransformChangedFn);

    /**
     * @brief Which space the current transform will be rescaled before applying
     * the matrix. It's useful to make the object the same size regardless the
     * distance to the camera.
     */
    OMNIUI_PROPERTY(Space, scaleTo, DEFAULT, Space::eCurrent, READ, getScaleTo, WRITE, setScaleTo);

    /**
     * @brief Rotates this transform to align the direction with the camera.
     */
    OMNIUI_PROPERTY(LookAt, lookAt, DEFAULT, LookAt::eNone, READ, getLookAt, WRITE, setLookAt);

    /**
     * @brief Set a basis to this transform. A basis defines a different/new transform space for thisTransform,
     * separate from any inherited hierarchy or existing, assumed space. As such, Transform objects with a non-null
     * basis will adhere to their basis and ignore any existing transform stack in their tree.
     *
     * @param basis The basis to set. Setting this to nullptr or an empty shared_ptr is valid.
     */
    OMNIUI_SCENE_API
    void setBasis(std::shared_ptr<TransformBasis> basis);

    /**
     * @brief Get the basis pointer for this Transform.
     *
     * @return std::shared_ptr<TransformBasis> This may be an empty shared_ptr.
     */
    OMNIUI_SCENE_API
    std::shared_ptr<TransformBasis> getBasis() const;

protected:
    /**
     * @brief Constructor
     */
    OMNIUI_SCENE_API
    Transform();

    OMNIUI_SCENE_API
    void _preDrawContent(
        const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height) override;

    OMNIUI_SCENE_API
    void _drawContent(const Matrix44& projection, const Matrix44& view) override;

    OMNIUI_SCENE_API
    Transform(const Matrix44& transform);

    void _dirtyTransform();

private:
    struct TransformData;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
