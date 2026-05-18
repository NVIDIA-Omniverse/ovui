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
#include "Object.h"

#include <memory>
#include <unordered_set>
#include <vector>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

class DrawBuffer;
class DrawBufferIndex;
struct DrawData;
class DrawList;
class AbstractGesture;



/**
 * @brief Represents the root of the scene and holds the shapes, gestures and
 * managers.
 */
class OMNIUI_SCENE_CLASS_API Scene : public AbstractContainer
{
    OMNIUI_SCENE_OBJECT(Scene);

public:
    OMNIUI_SCENE_API
    virtual ~Scene();

    OMNIUI_SCENE_API
    void destroy() override;

    /**
     * @brief Returns gesture manager used by default.
     */
    OMNIUI_SCENE_API
    const std::shared_ptr<GestureManager>& getDefaultGestureManager() const;

    /**
     * @brief Return the number of buffers used. Using for unit testing.
     */
    OMNIUI_SCENE_API
    size_t getDrawListBufferCount() const;

protected:
    friend class AbstractItem;
    friend class SceneView;

    OMNIUI_SCENE_API
    Scene();

    void _preDrawContent(
        const MouseInput&, const Matrix44& projection, const Matrix44& view, float width, float height) override;
    void _drawContent(const Matrix44& projection, const Matrix44& view) override;
    void _postDrawContent(const Matrix44& projection, const Matrix44& view) override;

    const DrawData& _getDrawData() const;
    DrawList* _getDrawList() const;
    DrawBufferIndex& _getDrawBufferIndex() override;

    const Scene* _getScene() const override
    {
        return this;
    }

    // Override this interface to always call _drawContent()
    bool _needDrawContent() override
    {
        return true;
    }

    template <typename T> T& _getData() const
    {
        return *m_data;
    }

    struct SceneData;
    std::unique_ptr<SceneData> m_data;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
