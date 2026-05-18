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

#include "Api.h"

#include <glm/glm.hpp>

#define _USE_MATH_DEFINES
#include <math.h>


OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

// Using double as default float type
using Float = double;

// TODO: This is a temporary placeholder. We need to implement all of this.
using Color4 = glm::vec<4, Float, glm::defaultp>;
using Vector2 = glm::vec<2, Float, glm::defaultp>;
using Vector3 = glm::vec<3, Float, glm::defaultp>;
using Vector4 = glm::vec<4, Float, glm::defaultp>;

/**
 * @brief Stores a 4x4 matrix of double elements. A basic type.
 *
 * Matrices are defined to be in row-major order.
 *
 * The matrix mode is required to define the matrix that resets the
 * transformation to fit the geometry into NDC, Screen space, or rotate it to
 * the camera direction.
 */
class Matrix44 : public glm::mat<4, 4, Float, glm::defaultp>
{
    using BaseType = glm::mat<4, 4, Float, glm::defaultp>;
public:
    // Constructor
    template <typename... Args>
    Matrix44(Args... args) : BaseType{ args... }
    {
    }

    // TODO: getTranslate
    // TODO: getRotate
    // TODO: getScale

    OMNIUI_SCENE_API
    Matrix44 getInverse() const;

    /**
     * @brief Test this matrix for equality against another one
     */
    OMNIUI_SCENE_API
    inline bool operator == (const Matrix44& rhs) const {
        return static_cast<const BaseType&>(*this) == static_cast<const BaseType&>(rhs);
    }

    /**
     * @brief Test this matrix for inequality against another one
     */
    OMNIUI_SCENE_API
    inline bool operator != (const Matrix44& rhs) const {
        return static_cast<const BaseType&>(*this) != static_cast<const BaseType&>(rhs);
    }

    /**
     * @brief Rotates the matrix to be aligned with the camera
     *
     * @param view The view matrix of the camera
     */
    OMNIUI_SCENE_API
    Matrix44& setLookAtView(Matrix44 view);

    /**
     * @brief Creates a matrix to specify a translation at the given coordinates
     */
    OMNIUI_SCENE_API
    static Matrix44 getTranslationMatrix(Float x, Float y, Float z);

    /**
     * @brief Creates a matrix to specify a rotation around each axis
     *
     * @param degrees true if the angles are specified in degrees
     */
    OMNIUI_SCENE_API
    static Matrix44 getRotationMatrix(Float x, Float y, Float z, bool degrees = false);

    /**
     * @brief Creates a matrix to specify a scaling with the given scale factor per axis
     */
    OMNIUI_SCENE_API
    static Matrix44 getScaleMatrix(Float x, Float y, Float z);
};

void createRay(const Matrix44& projection, const Matrix44& view, const Vector2& mouse, Vector3* rayOrigin, Vector3* rayDir);

bool lineLineFindClosestPoints(const Vector3& p11,
                               const Vector3& p12,
                               const Vector3& p21,
                               const Vector3& p22,
                               Vector3* closest1,
                               Vector3* closest2,
                               Float* t1,
                               Float* t2);

bool lineSegFindClosestPoints(const Vector3& p11,
                              const Vector3& p12,
                              const Vector3& p21,
                              const Vector3& p22,
                              Vector3* closest1,
                              Vector3* closest2,
                              Float* t1,
                              Float* t2);

bool raySegFindClosestPoints(const Vector3& rayOrigin,
                             const Vector3& rayDir,
                             const Vector3& p0,
                             const Vector3& p1,
                             Vector3* rayPoint,
                             Vector3* segPoint,
                             Float* rayDistance,
                             Float* segDistance);

bool raySegPlaneGesturePayload(const Vector3& rayOrigin,
                               const Vector3& rayDir,
                               const Vector3& p,
                               const Vector3& v1,
                               const Vector3& v2,
                               Vector3* gesturePayload,
                               Float* s,
                               Float* t);

void raySegFindClosestPoint(const Vector3& rayOrigin, const Vector3& rayDir, const Vector3& p, Vector3* closest, Float* t);

Float screenSpaceDistance(
    const Vector3& p1, const Vector3& p2, const Matrix44& projection, const Matrix44& view, const Vector2& frameSize);

template <typename T>
inline void _ensureCapacity(T& buffer, size_t capacity)
{
    if (buffer.capacity() < capacity)
    {
        buffer.reserve(capacity);
    }
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
