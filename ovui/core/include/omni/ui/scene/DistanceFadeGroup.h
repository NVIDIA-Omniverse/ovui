/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */
#pragma once

#include "Transform.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/** Camera-relative Gaussian opacity fade. Zero normal uses world distance.
 * A unit plane normal uses in-plane distance divided by camera height above
 * that plane. At/beyond end, opacity is exp(-pi*pi), as in legacy grids.
 */
struct DistanceFade
{
    bool enabled = false;
    Float start = 0.0;
    Float end = 1.0;
    Vector3 planeNormal{ 0.0 };
    bool operator==(const DistanceFade& other) const
    {
        return enabled == other.enabled && start == other.start && end == other.end &&
               planeNormal == other.planeNormal;
    }
};

/** Fade inherited by child shapes. Nested groups override their parent;
 * a disabled group removes the inherited fade. Parameters are world-space,
 * independent of the local transform. Requires SceneView.supportsDistanceFade().
 * Existing Transform behavior is unchanged.
 */
class OMNIUI_SCENE_CLASS_API DistanceFadeGroup : public Transform
{
    OMNIUI_SCENE_OBJECT(DistanceFadeGroup);
public:
    OMNIUI_SCENE_API
    const DistanceFade& getDistanceFade() const;
    /** Invalid distances or normals throw without changing existing state. */
    OMNIUI_SCENE_API
    void setDistanceFade(const DistanceFade& fade);
protected:
    OMNIUI_SCENE_API
    explicit DistanceFadeGroup(const DistanceFade& fade = {});
    OMNIUI_SCENE_API
    void _preDrawContent(const MouseInput&, const Matrix44&, const Matrix44&, float, float) override;
    OMNIUI_SCENE_API
    void _drawContent(const Matrix44&, const Matrix44&) override;
private:
    DistanceFade m_fade;
};

class DrawBuffer;
/** Borrowed identity, valid until the next scene draw or destruction. */
struct DistanceFadeDrawBuffer
{
    const DrawBuffer* buffer;
    DistanceFade fade;
    bool operator==(const DistanceFadeDrawBuffer& other) const
    {
        return buffer == other.buffer && fade == other.fade;
    }
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
