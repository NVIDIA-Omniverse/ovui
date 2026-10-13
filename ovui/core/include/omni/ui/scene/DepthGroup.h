/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "Transform.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/** Scoped depth behavior. Existing scenes retain their renderer's defaults. */
enum class DepthPolicy
{
    eInherit,
    eDefault,
    eTestOnly,
    eTestAndWrite,
    eOverlay,
};

/**
 * A transform whose descendants inherit a depth policy. A nested group can
 * override the policy. Overlay buffers render after depth-tested buffers;
 * ordering inside each pass is stable container order, not shape submission order.
 * Requires a SceneView that reports supportsDepthGroups().
 */
class OMNIUI_SCENE_CLASS_API DepthGroup : public Transform
{
    OMNIUI_SCENE_OBJECT(DepthGroup);
public:
    OMNIUI_SCENE_API
    ~DepthGroup() override;
    OMNIUI_SCENE_API
    DepthPolicy getDepthPolicy() const;
    OMNIUI_SCENE_API
    void setDepthPolicy(DepthPolicy policy);

protected:
    OMNIUI_SCENE_API
    explicit DepthGroup(DepthPolicy policy = DepthPolicy::eInherit);
    OMNIUI_SCENE_API
    void _preDrawContent(const MouseInput&, const Matrix44&, const Matrix44&, float, float) override;
    OMNIUI_SCENE_API
    void _drawContent(const Matrix44&, const Matrix44&) override;

private:
    friend class Scene;
    OMNIUI_SCENE_API
    static bool _hasInstances();
    DepthPolicy m_depthPolicy = DepthPolicy::eInherit;
};

class DrawBuffer;

/** Borrowed buffer identity, valid until the next scene draw or destruction. */
struct DepthDrawBuffer
{
    const DrawBuffer* buffer;
    DepthPolicy policy;

    bool operator==(const DepthDrawBuffer& other) const
    {
        return buffer == other.buffer && policy == other.policy;
    }
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
