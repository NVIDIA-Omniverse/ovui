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

#include "AbstractItem.h"
#include "ManipulatorModelHelper.h"

#include <omni/ui/ImageProvider/ImageProvider.h>
#include <omni/ui/Widget.h>

#include <memory>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

class AbstractDrawSystem;
class Scene;
class SceneViewPrivate;

/**
 * @brief The widget to render omni.ui.scene.
 */
class OMNIUI_SCENE_CLASS_API SceneView : public Widget, public ManipulatorModelHelper
{
    OMNIUI_OBJECT(SceneView)
protected:
    using TextureOptions = ImageProviderTextureOptions;

public:
    enum class AspectRatioPolicy : uint8_t
    {
        eStretch = 0,
        ePreserveAspectFit,
        ePreserveAspectCrop,
        ePreserveAspectVertical,
        ePreserveAspectHorizontal,
    };

    OMNIUI_SCENE_API
    ~SceneView() override;

    /**
     * @brief The camera projection matrix. It's a shortcut for
     * Matrix44(SceneView.model.get_as_floats("projection"))
     */
    OMNIUI_SCENE_API
    const Matrix44& getProjection() const;

    /**
     * @brief The camera view matrix. It's a shortcut for
     * Matrix44(SceneView.model.get_as_floats("view"))
     */
    OMNIUI_SCENE_API
    const Matrix44& getView() const;

    /**
     * @brief Called by the model when the model value is changed. The class should react to the changes.
     *
     * @param item The item in the model that is changed. If it's NULL, the root is changed.
     */
    OMNIUI_SCENE_API
    void onModelUpdated(const std::shared_ptr<const AbstractManipulatorModel::AbstractManipulatorItem>& item) override;

    /**
     * @brief Convert NDC 2D [-1..1] coordinates to 3D ray.
     */
    OMNIUI_SCENE_API
    void getRayFromNdc(const Vector2& ndc, Vector3* rayOrigin, Vector3* rayDirection) const;

    /**
     * @brief The container that holds the shapes, gestures and managers.
     */
    OMNIUI_PROPERTY(std::shared_ptr<Scene>, scene, READ, getScene, WRITE, setScene, PROTECTED, NOTIFY, _setSceneChangedFn);

    /**
     * @brief Aspect ratio of the rendering screen. This screen will be fit to the widget.
     *
     * SceneView simulates the behavior of the Kit viewport where the rendered
     * image (screen) fits into the viewport (widget), and the camera has
     * multiple policies that modify the camera projection matrix's aspect ratio
     * to match it to the screen aspect ratio.
     *
     * When screen_aspect_ratio is 0, Screen size matches the Widget bounds.
     *
     * \internal
     * +-Widget-------------+
     * |                    |
     * +-Screen-------------+
     * |                    |
     * |    +----+          |
     * |   /    /|          |
     * |  +----+ |          |
     * |  |    | +          |
     * |  |    |/           |
     * |  +----+            |
     * |                    |
     * +--------------------+
     * |                    |
     * +--------------------+
     * \endinternal
     */
    OMNIUI_PROPERTY(float, screenAspectRatio, DEFAULT, 0.0, READ, getScreenAspectRatio, WRITE, setScreenAspectRatio);

    /**
     * @brief When it's false, the mouse events from other widgets inside the
     * bounds are ignored. We need it to filter out mouse events from mouse
     * events of widgets in `ui.VStack(content_clipping=1)`.
     */
    OMNIUI_PROPERTY(bool, childWindowsInput, DEFAULT, true, READ, isChildWindowsInput, WRITE, setChildWindowsInput);

    /**
     * @brief Define what happens when the aspect ratio of the camera is
     * different from the aspect ratio of the widget.
     */
    OMNIUI_PROPERTY(AspectRatioPolicy,
                    aspectRatioPolicy,
                    DEFAULT,
                    AspectRatioPolicy::ePreserveAspectHorizontal,
                    READ,
                    getAspectRatioPolicy,
                    WRITE,
                    setAspectRatioPolicy);

    /**
     * @brief A switcher to control the draw buffer caching optimization.
     */
    OMNIUI_PROPERTY(bool,
                    cacheDrawBuffer,
                    DEFAULT,
                    false,
                    READ,
                    getCacheDrawBuffer,
                    WRITE,
                    setCacheDrawBuffer,
                    NOTIFY,
                    _setCacheDrawBufferChangedFn);

    Matrix44 getAmendedProjection() const;

    OMNIUI_SCENE_API
    virtual TextureOptions getTextureOptions() const;

protected:
    /**
     * Constructor.
     */
    OMNIUI_SCENE_API
    SceneView(const std::shared_ptr<AbstractManipulatorModel>& model = nullptr);

    /**
     * @brief Creates DrawSystem. By default creates ImGuiDrawSystem. The
     * developer can reimplement it to use a custom backend.
     */
    OMNIUI_SCENE_API
    virtual std::unique_ptr<AbstractDrawSystem> _createDrawSystem() const;

    /**
     * @brief Returns the mouse input object that has the information about 3D
     * position, orientation, buttons, etc. By default it takes the information
     * from ImGui, but the developer can override it to use a custom input
     * provider.
     */
    OMNIUI_SCENE_API
    virtual MouseInput _captureInput(float width, float height, const Matrix44& view, const Matrix44& projection) const;

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_SCENE_API
    void _drawContent(float elapsedTime) override;

    void _dirtyHierarchy();

protected:
    // Projection-view cache to avoid querying the model every frame.
    // The camera projection.
    Matrix44 m_projection;
    // The camera transform.
    Matrix44 m_view;

    std::unique_ptr<SceneViewPrivate> m_prv;
    std::unique_ptr<AbstractDrawSystem> m_draw;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
