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

#include <omni/ui/scene/Math.h>

#include <stdio.h>

#define printmatrix(m)                                                                                                 \
    printf(#m                                                                                                          \
           ":\n"                                                                                                       \
           "%f %f %f %f\n"                                                                                             \
           "%f %f %f %f\n"                                                                                             \
           "%f %f %f %f\n"                                                                                             \
           "%f %f %f %f\n",                                                                                            \
           m[0][0], m[0][1], m[0][2], m[0][3], m[1][0], m[1][1], m[1][2], m[1][3], m[2][0], m[2][1], m[2][2], m[2][3], \
           m[3][0], m[3][1], m[3][2], m[3][3]);


OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

#define EPS 1e-6

static inline bool _isClose(Float a, Float b, Float epsilon)
{
    return glm::abs(a - b) < epsilon;
}

static inline Vector3 _findClosestPoint(const Vector3& origin, const Vector3& dir, const Vector3& point, Float* t)
{
    // Compute the vector from the start point to the given point.
    Vector3 v = point - origin;

    // Find the length of the projection of this vector onto the line.
    Float len = glm::length(dir);
    Float lt = glm::dot(v, dir);
    if (len != 0.0)
    {
        lt = lt / (len * len);
    }

    if (t)
    {
        *t = lt;
    }

    return origin + dir * lt;
}

Matrix44 Matrix44::getInverse() const
{
    return glm::inverse(*this);
}

Matrix44& Matrix44::setLookAtView(Matrix44 view)
{
    view = view.getInverse();

    Float lenX = glm::length(Vector3{ (*this)[0][0], (*this)[0][1], (*this)[0][2] });
    Float lenY = glm::length(Vector3{ (*this)[1][0], (*this)[1][1], (*this)[1][2] });
    Float lenZ = glm::length(Vector3{ (*this)[2][0], (*this)[2][1], (*this)[2][2] });

    // The view direction
    Vector3 camX = glm::normalize(Vector3{ view[0][0], view[0][1], view[0][2] });
    Vector3 camY = glm::normalize(Vector3{ view[1][0], view[1][1], view[1][2] });
    Vector3 camZ = glm::normalize(Vector3{ view[2][0], view[2][1], view[2][2] });

    // Turn the camera to the direction of view and keep the scale
    (*this)[0][0] = camX[0] * lenX;
    (*this)[0][1] = camX[1] * lenX;
    (*this)[0][2] = camX[2] * lenX;
    (*this)[1][0] = camY[0] * lenY;
    (*this)[1][1] = camY[1] * lenY;
    (*this)[1][2] = camY[2] * lenY;
    (*this)[2][0] = camZ[0] * lenZ;
    (*this)[2][1] = camZ[1] * lenZ;
    (*this)[2][2] = camZ[2] * lenZ;

    return *this;
}

Matrix44 Matrix44::getTranslationMatrix(Float x, Float y, Float z)
{
    return Matrix44{ 1.0, 0.0, 0.0, 0.0, //
                     0.0, 1.0, 0.0, 0.0, //
                     0.0, 0.0, 1.0, 0.0, //
                     x,   y,   z,   1.0 };
}

Matrix44 Matrix44::getRotationMatrix(Float x, Float y, Float z, bool degrees)
{
    if (degrees)
    {
        x *= Float(M_PI / 180.0);
        y *= Float(M_PI / 180.0);
        z *= Float(M_PI / 180.0);
    }

    Matrix44 result{ (Float)1.0 };
    if (x != 0.0)
    {
        Float c = glm::cos(x);
        Float s = glm::sin(x);
        result = result * Matrix44{ 1.0, 0.0, 0.0, 0.0, //
                                    0.0, c,   s,   0.0, //
                                    0.0, -s,  c,   0.0, //
                                    0.0, 0.0, 0.0, 1.0 };
    }
    if (y != 0.0)
    {
        Float c = glm::cos(y);
        Float s = glm::sin(y);
        result = result * Matrix44{ c,   0.0, -s,  0.0, //
                                    0.0, 1.0, 0.0, 0.0, //
                                    s,   0.0, c,   0.0, //
                                    0.0, 0.0, 0.0, 1.0 };
    }
    if (z != 0.0)
    {
        Float c = glm::cos(z);
        Float s = glm::sin(z);
        result = result * Matrix44{ c,   s,   0.0, 0.0, //
                                    -s,  c,   0.0, 0.0, //
                                    0.0, 0.0, 1.0, 0.0, //
                                    0.0, 0.0, 0.0, 1.0 };
    }

    return result;
}

Matrix44 Matrix44::getScaleMatrix(Float x, Float y, Float z)
{
    // TODO: warning when the space is unknown. We will have it when we have rotation.
    // We can use OMNIUI_LOG_ERROR_ONCE to not polute output.
    return { x,   0.0, 0.0, 0.0, //
             0.0, y,   0.0, 0.0, //
             0.0, 0.0, z,   0.0, //
             0.0, 0.0, 0.0, 1.0 };
}

void createRay(const Matrix44& projection, const Matrix44& view, const Vector2& mouse, Vector3* rayOrigin, Vector3* rayDir)
{
    // TODO: Write it to stop using glm
    Matrix44 inverse{ glm::inverse(projection * view) };
    Vector4 origin = inverse * Vector4{ mouse.x, mouse.y, 0.0, 1.0 };
    origin /= origin.w;

    if (rayOrigin)
    {
        *rayOrigin = Vector3{ origin.x, origin.y, origin.z };
    }

    if (rayDir)
    {
        if (projection[3][3] == 1)
        {
            // Orthographic ray is constant across the plane, as view forward.
            *rayDir = glm::normalize(Vector3(view[0][2], view[1][2], view[2][2]));
        }
        else
        {
            Vector4 dir = inverse * Vector4{ mouse.x, mouse.y, 0.5, 1.0 };
            dir /= dir.w;
            *rayDir = glm::normalize(Vector3{ dir.x - origin.x, dir.y - origin.y, dir.z - origin.z });
        }
    }
}

// Source: GfFindClosestPoints
bool lineLineFindClosestPoints(const Vector3& p11,
                               const Vector3& p12,
                               const Vector3& p21,
                               const Vector3& p22,
                               Vector3* closest1,
                               Vector3* closest2,
                               Float* t1,
                               Float* t2)
{
    // Define terms:
    //   p1 = line 1's position
    //   d1 = line 1's direction
    //   p2 = line 2's position
    //   d2 = line 2's direction
    const Vector3& p1 = p11;
    const Vector3 d1 = (p12 - p11);
    const Vector3& p2 = p21;
    const Vector3 d2 = (p22 - p21);

    // We want to find points closest1 and closest2 on each line.
    // Their parametric definitions are:
    //   closest1 = p1 + t1 * d1
    //   closest2 = p2 + t2 * d2
    //
    // We know that the line connecting closest1 and closest2 is
    // perpendicular to both the ray and the line segment. So:
    //   d1 . (closest2 - closest1) = 0
    //   d2 . (closest2 - closest1) = 0
    //
    // Substituting gives us:
    //   d1 . [ (p2 + t2 * d2) - (p1 + t1 * d1) ] = 0
    //   d2 . [ (p2 + t2 * d2) - (p1 + t1 * d1) ] = 0
    //
    // Rearranging terms gives us:
    //   t2 * (d1.d2) - t1 * (d1.d1) = d1.p1 - d1.p2
    //   t2 * (d2.d2) - t1 * (d2.d1) = d2.p1 - d2.p2
    //
    // Substitute to simplify:
    //   a = d1.d2
    //   b = d1.d1
    //   c = d1.p1 - d1.p2
    //   d = d2.d2
    //   e = d2.d1 (== a, if you're paying attention)
    //   f = d2.p1 - d2.p2
    Float a = glm::dot(d1, d2);
    Float b = glm::dot(d1, d1);
    Float c = glm::dot(d1, p1) - glm::dot(d1, p2);
    Float d = glm::dot(d2, d2);
    Float e = a;
    Float f = glm::dot(d2, p1) - glm::dot(d2, p2);

    // And we end up with:
    //  t2 * a - t1 * b = c
    //  t2 * d - t1 * e = f
    //
    // Solve for t1 and t2:
    //  t1 = (c * d - a * f) / (a * e - b * d)
    //  t2 = (c * e - b * f) / (a * e - b * d)
    //
    // Note the identical denominators...
    Float denom = a * e - b * d;

    // Denominator == 0 means the lines are parallel; no intersection.
    if (_isClose(denom, 0, Float(EPS)))
    {
        return false;
    }

    Float lt1 = (c * d - a * f) / denom;
    Float lt2 = (c * e - b * f) / denom;

    if (closest1)
    {
        *closest1 = p1 + d1 * lt1;
    }

    if (closest2)
    {
        *closest2 = p2 + d2 * lt2;
    }

    if (t1)
    {
        *t1 = lt1;
    }

    if (t2)
    {
        *t2 = lt2;
    }

    return true;
}

// p11-p12 - line
// p21-p22 - segment
bool lineSegFindClosestPoints(const Vector3& p11,
                              const Vector3& p12,
                              const Vector3& p21,
                              const Vector3& p22,
                              Vector3* closest1,
                              Vector3* closest2,
                              Float* t1,
                              Float* t2)
{
    Vector3 cp1, cp2;
    Float lt1, lt2;
    if (!lineLineFindClosestPoints(p11, p12, p21, p22, &cp1, &cp2, &lt1, &lt2))
    {
        return false;
    }

    lt2 = glm::clamp(lt2, Float(0.0), Float(1.0));
    cp2 = p21 + (p22 - p21) * lt2;

    // If we clamp the line segment, change the rayPoint to be
    // the closest point on the ray to the clamped point.
    if (lt2 <= 0.0 || lt2 >= 1.0)
    {
        cp1 = _findClosestPoint(p11, (p12 - p11), cp2, &lt1);
    }

    if (closest1)
    {
        *closest1 = cp1;
    }

    if (closest2)
    {
        *closest2 = cp2;
    }

    if (t1)
    {
        *t1 = lt1;
    }

    if (t2)
    {
        *t2 = lt2;
    }

    return true;
}

bool raySegFindClosestPoints(const Vector3& rayOrigin,
                             const Vector3& rayDir,
                             const Vector3& p0,
                             const Vector3& p1,
                             Vector3* rayPoint,
                             Vector3* segPoint,
                             Float* rayDistance,
                             Float* segDistance)
{
    Vector3 rp, sp;
    Float rd, sd;
    if (!lineSegFindClosestPoints(rayOrigin, rayOrigin + rayDir, p0, p1, &rp, &sp, &rd, &sd))
    {
        return false;
    }

    if (rd < 0.0)
    {
        rd = 0.0;
    }

    if (rayPoint)
    {
        *rayPoint = rayOrigin + rayDir * rd;
    }

    if (segPoint)
    {
        *segPoint = sp;
    }

    if (rayDistance)
    {
        *rayDistance = rd;
    }

    if (segDistance)
    {
        *segDistance = sd;
    }

    return true;
}

bool raySegPlaneGesturePayload(const Vector3& rayOrigin,
                               const Vector3& rayDir,
                               const Vector3& p,
                               const Vector3& v1,
                               const Vector3& v2,
                               Vector3* intersection,
                               Float* s,
                               Float* t)
{
    Vector3 normal = glm::cross(v1, v2);
    Float denom = glm::dot(normal, rayDir);

    if (abs(denom) < EPS)
    {
        return false;
    }

    Float distance = glm::dot(p - rayOrigin, normal) / denom;
    if (distance < EPS)
    {
        return false;
    }

    *intersection = rayOrigin + rayDir * distance;
    Vector3 vi = *intersection - p;

    Vector3 n1 = glm::cross(v1, vi);
    Vector3 n2 = glm::cross(vi, v2);

    Float normal_length_square = glm::dot(normal, normal);
    // We use EPS * EPS because since we don't normalize the normal, and the
    // normal length can be very small if the triangle is small. Here we only
    // need to check if it's not 0, but we can't use 0 because there can be
    // precision errors.
    if (normal_length_square < EPS * EPS)
    {
        return false;
    }

    if (s)
    {
        // using a * sinC = c * sinA
        // simplify
        // Float l_vi = glm::length(vi);
        // Float l_v1 = glm::length(v1);
        // Float l_v2 = glm::length(v2);
        // Float sin_p0 = glm::length(normal)/(l_v1 * l_v2);
        // Float sin_v1 = glm::length(n2)/(l_vi * l_v2);
        // *s =  sin_v1 * l_vi / sin_p0 / l_v1;
        // get glm::length(n2)/glm::length(normal);
        *s =  glm::dot(n2, normal)/normal_length_square;
    }
    if (t)
    {
        // using a * sinC = c * sinA
        // simplify
        // Float l_vi = glm::length(vi);
        // Float l_v1 = glm::length(v1);
        // Float l_v2 = glm::length(v2);
        // Float sin_p0 = glm::length(normal)/(l_v1 * l_v2);
        // Float sin_v2 = glm::length(n1)/(l_vi * l_v1);
        // *t = sin_v2 * l_vi / sin_p0 / l_v2;
        // get glm::length(n1)/glm::length(normal);
        *t = glm::dot(n1, normal)/normal_length_square;
    }

    return true;
}

void raySegFindClosestPoint(const Vector3& rayOrigin, const Vector3& rayDir, const Vector3& p, Vector3* closest, Float* t)
{
    // Compute the vector from the start point to the given point.
    Vector3 v = p - rayOrigin;

    // Find the length of the projection of this vector onto the line.
    Float lt = glm::dot(v, rayDir);

    if (t)
    {
        *t = lt;
    }

    if (closest)
    {
        *closest = rayOrigin + rayDir * lt;
    }
}

Float screenSpaceDistance(
    const Vector3& p1, const Vector3& p2, const Matrix44& projection, const Matrix44& view, const Vector2& frameSize)
{
    // Convert them to screen space
    Vector4 first{ p1, 1.0 };
    Vector4 second{ p2, 1.0 };

    const Matrix44 transform{ (Float)1.0 };
    const Matrix44 pvc = projection * view * transform;

    first = pvc * first;
    second = pvc * second;

    first = first / first.w;
    second = second / second.w;

    // Get screen space distance
    Float x = (second.x - first.x) * frameSize.x * (Float)0.5;
    Float y = (second.y - first.y) * frameSize.y * (Float)0.5;
    return sqrt(x * x + y * y);
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE

#undef printmatrix
#undef EPS
