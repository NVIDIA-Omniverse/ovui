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
#include "Math.h"
#include "Object.h"
#include "Space.h"

#include <omni/ui/Callback.h>
#include <omni/ui/Property.h>

#include <memory>
#include <unordered_set>

OMNIUI_NAMESPACE_USING_DIRECTIVE

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

class Scene;
class SceneView;
class DrawList;
class GestureManager;

struct MouseInput
{
    MouseInput(const Vector2& inMouse = {},
               const Vector2& inMouseWheel = {},
               const Vector3& inMouseOrigin = {},
               const Vector3& inMouseDirection = {},
               const uint32_t& inModifiers = {},
               const uint32_t& inClicked = {},
               const uint32_t& inDoubleClicked = {},
               const uint32_t& inReleased = {},
               const uint32_t& inDown = {})
        : mouse{ inMouse },
          mouseWheel{ inMouseWheel },
          mouseOrigin{ inMouseOrigin },
          mouseDirection{ inMouseDirection },
          modifiers{ inModifiers },
          clicked{ inClicked },
          doubleClicked{ inDoubleClicked },
          released{ inReleased },
          down{ inDown }
    {
    }

    Vector2 mouse;
    Vector2 mouseWheel;
    Vector3 mouseOrigin;
    Vector3 mouseDirection;
    uint32_t modifiers;
    uint32_t clicked;
    uint32_t doubleClicked;
    uint32_t released;
    uint32_t down;
};

class OMNIUI_SCENE_CLASS_API AbstractItem : public std::enable_shared_from_this<AbstractItem>,
                                            protected omni::ui::CallbackHelper<AbstractItem>
{
public:

    enum class DirtyReason
    {
        kDirtyReasonContentChanged = 0,
        kDirtyReasonDescendantChanged,
    };

    OMNIUI_SCENE_API
    virtual ~AbstractItem();

    /**
     * @brief Removes all the callbacks and circular references.
     */
    OMNIUI_SCENE_API
    virtual void destroy();

    // We assume that all the operations with all the items should be performed with smart pointers because we have
    // parent-child relationships, and we automatically put new items to parents in the create method of every item.
    // If the object is copied or moved, it will break the Item-Container hierarchy.
    // No copy
    AbstractItem(const AbstractItem&) = delete;
    // No copy-assignment
    AbstractItem& operator=(const AbstractItem&) = delete;
    // No move constructor and no move-assignments are allowed because of the C++ standard

    OMNIUI_SCENE_API
    void preDrawContent(const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height);
    OMNIUI_SCENE_API
    void drawContent(const Matrix44& projection, const Matrix44& view);
    OMNIUI_SCENE_API
    void postDrawContent(const Matrix44& projection, const Matrix44& view);

    /**
     * @brief Transform the given point from the coordinate system fromspace to
     * the coordinate system tospace.
     */
    OMNIUI_SCENE_API
    virtual Vector3 transformSpace(Space fromSpace, Space toSpace, const Vector3& point) const;

    /**
     * @brief Transform the given vector from the coordinate system fromspace to
     * the coordinate system tospace.
     */
    OMNIUI_SCENE_API
    virtual Vector4 transformSpace(Space fromSpace, Space toSpace, const Vector4& vector) const;

    /**
     * @brief Calculate the effective visibility of this prim, as defined by its
     * most ancestral invisible opinion, if any.
     */
    OMNIUI_SCENE_API
    bool computeVisibility() const;

    OMNIUI_SCENE_API
    void forceDirty(DirtyReason reason);

    OMNIUI_SCENE_API
    bool needDrawContent();

    OMNIUI_PROPERTY(const AbstractContainer*, parent, DEFAULT, nullptr, READ_VALUE, getParent, PROTECTED, WRITE, _setParent);
    OMNIUI_PROPERTY(const Scene*, scene, DEFAULT, nullptr, PROTECTED, READ_VALUE, _getScene, WRITE, setScene);

    /**
     * @brief The current SceneView this item is parented to.
     */
    OMNIUI_PROPERTY(SceneView const*, sceneView, DEFAULT, nullptr, READ_VALUE, getSceneView, PROTECTED, WRITE, _setSceneView);

    /**
     * @brief This property holds whether the item is visible.
     */
    OMNIUI_PROPERTY(
        bool, visible, DEFAULT, true, READ, isVisible, WRITE, setVisible, PROTECTED, NOTIFY, _setVisibleChangedFn);

protected:
    friend class AbstractContainer;
    friend class SceneContainerStack;
    struct AbstractItemData;

    OMNIUI_SCENE_API
    virtual void _preDrawContent(
        const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height);
    OMNIUI_SCENE_API
    virtual void _drawContent(const Matrix44& projection, const Matrix44& view) = 0;
    OMNIUI_SCENE_API
    virtual void _postDrawContent(const Matrix44& projection, const Matrix44& view);

    OMNIUI_SCENE_API
    AbstractItem(AbstractItemData* = nullptr);

    OMNIUI_SCENE_API
    DrawList* _getDrawList() const;

    OMNIUI_SCENE_API
    virtual void _collectManagers(std::unordered_set<GestureManager*>& managers) const = 0;

    OMNIUI_SCENE_API
    virtual void _forceDirty(DirtyReason reason);

    OMNIUI_SCENE_API
    virtual bool _needDrawContent();

    template <typename T> T& _getData() const { return static_cast<T&>(*m_itemData); }

private:
    std::unique_ptr<AbstractItemData> m_itemData;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
