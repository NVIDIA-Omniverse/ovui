/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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

    /** Backends opt in during construction, without allocating a draw system. */
    OMNIUI_SCENE_API
    void _setSupportsDepthGroups(bool supported);
    OMNIUI_SCENE_API
    void _setSupportsMeshLighting(bool supported);
    OMNIUI_SCENE_API
    void _setSupportsDistanceFade(bool supported);
    OMNIUI_SCENE_API
    void _setSupportsWorldSpaceWidths(bool supported);
    OMNIUI_SCENE_API
    void _setSupportsPixelDiameterWidths(bool supported);

public:
    /** Whether this draw system implements scoped depth groups. */
    OMNIUI_SCENE_API
    bool supportsDepthGroups() const;
    /** Whether this draw system supports PolygonMesh headlight lighting. */
    OMNIUI_SCENE_API
    bool supportsMeshLighting() const;
    /** Whether child shapes can inherit a DistanceFadeGroup opacity fade. */
    OMNIUI_SCENE_API
    bool supportsDistanceFade() const;
    /** Whether Curve/Line/Points can use camera-facing world-space widths. */
    OMNIUI_SCENE_API
    bool supportsWorldSpaceWidths() const;
    /** Whether strokes can use physical pixel diameters with Hermite coverage. */
    OMNIUI_SCENE_API
    bool supportsPixelDiameterWidths() const;

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

    /** Collect an attached view using its normal layout, input and camera.
     * A backend publishing explicit frame identities may collect an empty scene
     * to clear its previous image and complete a transparent frame. False keeps
     * the ordinary behavior of releasing the draw system when no geometry exists.
     * Returns true only when this call collected a frame for the draw system.
     * Nonvirtual: existing SceneView layout and virtual dispatch are unchanged.
     */
    OMNIUI_SCENE_API
    bool _collectAttachedFrame(float elapsedTime, bool collectEmptyScene);

    /** Collect an unattached view with explicit camera/pixel dimensions and no
     * input. For offscreen-capable backends on the UI thread with their graphics
     * context active. Returns false during renderer initialization. The caller
     * schedules rendering separately; this method never pumps UI/app events.
     * Nonvirtual: existing published SceneView layout and widget drawing are unchanged.
     */
    OMNIUI_SCENE_API
    bool _collectOffscreenFrame(uint32_t width, uint32_t height, const Matrix44& projection,
                               const Matrix44& view, float dpiScale = 1.0f);

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
