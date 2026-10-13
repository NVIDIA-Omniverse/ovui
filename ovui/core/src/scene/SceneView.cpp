/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

// NOTE: include imgui_internal.h BEFORE the omni/ui/scene headers, which pull in
// OMNIUI_NAMESPACE_USING_DIRECTIVE (`using namespace omni::ui;` at global scope)
// via AbstractItem.h. Without this order, imgui_internal.h's
// `inline double ImLog(double x) { return log(x); }` sees the `omni::ui::log`
// namespace as a candidate for unqualified `log` lookup and the call becomes
// ambiguous against `::log` from <cmath>.
#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>

#include <omni/ui/scene/SceneView.h>

#include <omni/ui/platform/Assert.h>
#include <omni/ui/platform/Log.h>

#include <omni/ui/scene/GestureModifiers.h>
#include <omni/ui/scene/DrawBuffer.h>
#include <omni/ui/scene/DrawList.h>
#include <omni/ui/scene/CameraModel.h>
#include <omni/ui/scene/ImguiDrawSystem.h>
#include <omni/ui/scene/Math.h>
#include <omni/ui/scene/Scene.h>
#include <omni/ui/scene/SceneContainerScope.h>

#include <algorithm>
#include <cmath>
#include <mutex>
#include <stdexcept>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

static constexpr uint64_t kProfilerMask = 1;

/**
 * @brief Modifies the given projection matrix according to the policy and to
 * the given aspect ratio of the screen.
 *
 * Ported from CameraUtilConformedWindow (RenderDelegate.cpp)
 *
 * @todo It's copy-pasted. We need to use shared code.
 */
static Matrix44 CameraUtilConformedWindow(SceneView::AspectRatioPolicy policy, Float resAspect, const Matrix44& projIn)
{
    using CameraFit = SceneView::AspectRatioPolicy;
    if (policy == CameraFit::eStretch)
    {
        return projIn;
    }

    auto _SafeDiv = [](const Float a, const Float b) -> Float { return (b != 0.0) ? (a / b) : a; };
    auto _Sign = [](const Float x) -> Float { return (x < (Float)0.0) ? (Float)-1.0 : (Float)1.0; };
    auto _ResolveConformWindowPolicy = [](CameraFit policy, Float fovAspect, Float resAspect) -> CameraFit {
        if ((policy == CameraFit::ePreserveAspectVertical) || (policy == CameraFit::ePreserveAspectHorizontal))
        {
            return policy;
        }
        if ((policy == CameraFit::ePreserveAspectFit) ^ (fovAspect > resAspect))
        {
            return CameraFit::ePreserveAspectVertical;
        }
        return CameraFit::ePreserveAspectHorizontal;
    };

    Matrix44 result(projIn);

    const Float projectionMatrix_0_0 = projIn[0][0];
    const Float projectionMatrix_1_1 = projIn[1][1];

    // The aspect ratio of the frustum corresponding to the given
    // projectionMatrix (assume is square pixels) is given by the ratio of
    // the two top diaognal entries.
    // Note: usually the aspect ratio is given by width / height, so one might
    // expect to see the first diagonal entry divided by the second entry.
    // However, since these parameters are used in the persepctive division,
    // they behave the other way around.
    // Also note that we take the absolute value here and use _Sign later
    // to restore the signs to support mirroring.

    const Float window[] = { std::abs(projectionMatrix_1_1), std::abs(projectionMatrix_0_0) };
    const Float fovAspect = _SafeDiv(window[0], window[1]);

    // This tells us whether we need to adjust the parameters affecting the
    // vertical or horizontal aspects of the projectionMatrix.
    const auto resolvedPolicy = _ResolveConformWindowPolicy(policy, fovAspect, resAspect);

    if (resolvedPolicy == CameraFit::ePreserveAspectHorizontal)
    {
        // Adjust vertical size
        result[1][1] = _Sign(projectionMatrix_1_1) * window[1] * resAspect;

        // Now handle the case that the frustum is asymetric, e.g., the angle
        // on the left is different from the angle on the right.
        // First compute the factor by which we scaled vertically...
        const Float scaleFactor = _SafeDiv(result[1][1], projectionMatrix_1_1);

        // ...and then apply it to the offsets making the frustum asymetric.
        // This one is important for perspective:
        result[2][1] *= scaleFactor;
        // This one is important for orthographic:
        result[3][1] *= scaleFactor;
    }
    else
    {
        // As above, but horizontally.
        result[0][0] = _Sign(projectionMatrix_0_0) * _SafeDiv(window[0], resAspect);

        const Float scaleFactor = _SafeDiv(result[0][0], projectionMatrix_0_0);

        result[2][0] *= scaleFactor;
        result[3][0] *= scaleFactor;
    }

    return result;
}

class SceneViewPrivate
{
public:
    std::mutex m_viewLock;
    bool m_supportsDepthGroups = false;
    bool m_supportsDistanceFade = false;
    bool m_supportsWorldSpaceWidths = false;
    bool m_supportsPixelDiameterWidths = false;
    bool m_supportsMeshLighting = false;
    // Borrowed only during synchronous collection of a dedicated offscreen view.
    const Matrix44* m_offscreenProjection = nullptr;
    const Matrix44* m_offscreenView = nullptr;
    // TODO: std::mutex m_projectionLock;
};

SceneView::SceneView(const std::shared_ptr<AbstractManipulatorModel>& model)
    : Widget{}, ManipulatorModelHelper{ model }, m_prv{ std::make_unique<SceneViewPrivate>() }
{
    if (!model)
    {
        // Default is CameraModel
        this->setModel(std::make_shared<CameraModel>(Matrix44{ (Float)1.0 }, Matrix44{ (Float)1.0 }));
    }

    this->onModelUpdated(nullptr);

    this->_setSceneChangedFn([this](const std::shared_ptr<Scene>& scene) { scene->_setSceneView(this); });

    this->_setCacheDrawBufferChangedFn(
        [this](const bool& caching)
        {
            if (!caching)
            {
                this->_dirtyHierarchy();
            }
        });

    OMNIUI_SCENE_WITH_CONTAINER(nullptr)
    {
        auto scene = Scene::create();

        this->setScene(scene);
    }
}

SceneView::~SceneView()
{
    const auto& scene = this->getScene();
    if (scene)
    {
        if (scene->getSceneView() != this)
        {
            scene->destroy();
        }
    }
}

const Matrix44& SceneView::getProjection() const
{
    return m_prv->m_offscreenProjection ? *m_prv->m_offscreenProjection : m_projection;
}

const Matrix44& SceneView::getView() const
{
    return m_prv->m_offscreenView ? *m_prv->m_offscreenView : m_view;
}

void SceneView::onModelUpdated(const std::shared_ptr<const AbstractManipulatorModel::AbstractManipulatorItem>& item)
{
    bool changedAll = false;
    if (!item)
    {
        changedAll = true;
    }

    const auto& model = this->getModel();
    OMNIUI_ASSERT(model);

    auto projection = model->getItem("projection");
    if (projection)
    {
        if (changedAll || item.get() == projection.get())
        {
            auto list = model->getAsFloats(projection);
            if (list.size() == 16)
            {
                m_projection = Matrix44{ list[0], list[1], list[2],  list[3],  list[4],  list[5],  list[6],  list[7],
                                         list[8], list[9], list[10], list[11], list[12], list[13], list[14], list[15] };
            }
            else
            {
                OMNIUI_LOG_ERROR("SceneView expects a 'projection' item to contain 16 floats, not %zu", list.size());
            }
        }
    }

    auto view = model->getItem("view");
    if (view)
    {
        if (changedAll || item.get() == view.get())
        {
            std::lock_guard<std::mutex> lock(m_prv->m_viewLock);

            auto list = model->getAsFloats(view);
            if (list.size() == 16)
            {
                m_view = Matrix44{ list[0], list[1], list[2],  list[3],  list[4],  list[5],  list[6],  list[7],
                                   list[8], list[9], list[10], list[11], list[12], list[13], list[14], list[15] };
            }
            else
            {
                OMNIUI_LOG_ERROR("SceneView expects a 'view' item to contain 16 floats, not %zu", list.size());
            }
        }
    }
}

void SceneView::getRayFromNdc(const Vector2& ndc, Vector3* rayOrigin, Vector3* rayDirection) const
{
    Matrix44 projection = this->getAmendedProjection();
    Matrix44 view;
    {
        std::lock_guard<std::mutex> lock(m_prv->m_viewLock);
        view = this->getView();
    }
    createRay(projection, view, ndc, rayOrigin, rayDirection);
}

std::unique_ptr<AbstractDrawSystem> SceneView::_createDrawSystem() const
{
    return std::make_unique<ImguiDrawSystem>();
}

MouseInput SceneView::_captureInput(float width, float height, const Matrix44& view, const Matrix44& projection) const
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    // Get the input from ImGui
    bool isWindowHovered;
    if (this->isChildWindowsInput())
    {
        isWindowHovered = ImGui::IsWindowHovered(ImGuiHoveredFlags_ChildWindows);
    }
    else
    {
        // Filter out mouse events of widgets in `ui.VStack(content_clipping=1)`
        auto ctx = ImGui::GetCurrentContext();
        OMNIUI_ASSERT(ctx);
        isWindowHovered = ctx->CurrentWindow == ctx->HoveredWindow;
    }

    // Capture input
    const ImGuiIO& io = ImGui::GetIO();
    ImVec2 cursor = ImGui::GetCursorScreenPos();

    Vector2 mouse{ -1.0 + 2.0 * (io.MousePos.x - cursor.x) / width, 1.0 - 2.0 * (io.MousePos.y - cursor.y) / height };
    Vector2 mouseWheel;
    uint32_t clicked;
    uint32_t doubleClicked;
    // Also check for the hovering status from the base widget class to ensure we are inside the scene view.
    if (isHovered() && isWindowHovered)
    {
        clicked = ImGui::IsMouseClicked(0) << 0 | ImGui::IsMouseClicked(1) << 1 | ImGui::IsMouseClicked(2) << 2;
        doubleClicked = ImGui::IsMouseDoubleClicked(0) << 0 | ImGui::IsMouseDoubleClicked(1) << 1 |
                        ImGui::IsMouseDoubleClicked(2) << 2;
        mouseWheel = Vector2{ io.MouseWheelH, io.MouseWheel };
    }
    else
    {
        clicked = 0;
        doubleClicked = 0;
        mouseWheel = Vector2{ 0.0f, 0.0f };
    }
    uint32_t released = ImGui::IsMouseReleased(0) << 0 | ImGui::IsMouseReleased(1) << 1 | ImGui::IsMouseReleased(2) << 2;
    uint32_t down = ImGui::IsMouseDown(0) << 0 | ImGui::IsMouseDown(1) << 1 | ImGui::IsMouseDown(2) << 2;
    uint32_t modifiers = (io.KeyAlt ? kModifierFlagAlt : 0) |
                         (io.KeyShift ? kModifierFlagShift : 0) |
                         (io.KeyCtrl ? kModifierFlagControl : 0) |
                         (io.KeySuper ? kModifierFlagSuper : 0);

    // Ray direction
    Vector3 mouseOrigin;
    Vector3 mouseDirection;
    createRay(projection, view, mouse, &mouseOrigin, &mouseDirection);

    return { mouse, mouseWheel, mouseOrigin, mouseDirection, modifiers, clicked, doubleClicked, released, down };
}

bool SceneView::supportsMeshLighting() const
{
    return m_prv->m_supportsMeshLighting;
}

void SceneView::_setSupportsMeshLighting(bool supported)
{
    m_prv->m_supportsMeshLighting = supported;
}

bool SceneView::supportsDepthGroups() const
{
    return m_prv->m_supportsDepthGroups;
}

void SceneView::_setSupportsDepthGroups(bool supported)
{
    m_prv->m_supportsDepthGroups = supported;
}

bool SceneView::supportsDistanceFade() const
{
    return m_prv->m_supportsDistanceFade;
}

void SceneView::_setSupportsDistanceFade(bool supported)
{
    m_prv->m_supportsDistanceFade = supported;
}

bool SceneView::supportsWorldSpaceWidths() const
{
    return m_prv->m_supportsWorldSpaceWidths;
}

bool SceneView::supportsPixelDiameterWidths() const
{
    return m_prv->m_supportsPixelDiameterWidths;
}

void SceneView::_setSupportsPixelDiameterWidths(bool supported)
{
    m_prv->m_supportsPixelDiameterWidths = supported;
}

void SceneView::_setSupportsWorldSpaceWidths(bool supported)
{
    m_prv->m_supportsWorldSpaceWidths = supported;
}

void SceneView::_drawContent(float elapsedTime)
{
    _collectAttachedFrame(elapsedTime, false);
}

bool SceneView::_collectAttachedFrame(float elapsedTime, bool collectEmptyScene)
{
    if (!this->isEnabled())
    {
        return false;
    }

    OMNIUI_PROFILE_ZONE("SceneView[%s]::_drawContent", getName().c_str());

    if (!this->isVisible())
    {
        OMNIUI_PROFILE_VERBOSE_ZONE("SceneView[%s]::_drawContent", "AbstractDrawSystem::reset");
        m_draw.reset();
        return false;
    }

    bool clearDraw = true;

    if (m_scene)
    {
        const float width = this->getComputedContentWidth();
        const float height = this->getComputedContentHeight();
        const Matrix44 projection = this->getAmendedProjection();
        const float dpiScale = this->getDpiScale();

        if (m_scene->getSceneView() == this)
        {
            Matrix44 view;
            {
                OMNIUI_PROFILE_VERBOSE_ZONE("SceneView[%s]::_drawContent - view unlocked", getName().c_str());
                std::lock_guard<std::mutex> lock(m_prv->m_viewLock);
                OMNIUI_PROFILE_VERBOSE_ZONE("SceneView[%s]::_drawContent - view locked", getName().c_str());
                view = this->getView();
            }

            const MouseInput input = this->_captureInput(width, height, view, projection);

            // Create the buffers.
            // NOTE: preDrawContent call must be balanced with postDrawContent so no early exit is allowed.
            // This is a requirement for AbstractContainer and Manipulator doing cleanup.
            //
            {
                OMNIUI_PROFILE_VERBOSE_ZONE("SceneView[%s]::_drawContent - Scene::preDrawContent", getName().c_str());
                m_scene->preDrawContent(input, projection, view, width / dpiScale, height / dpiScale);
            }
            {
                OMNIUI_PROFILE_VERBOSE_ZONE("SceneView[%s]::_drawContent - Scene::drawContent", getName().c_str());
                m_scene->drawContent(projection, view);
            }
            {
                OMNIUI_PROFILE_VERBOSE_ZONE("SceneView[%s]::_drawContent - Scene::postDrawContent", getName().c_str());
                m_scene->postDrawContent(projection, view);
            }
        }

        // Render the buffers
        OMNIUI_PROFILE_VERBOSE_ZONE("SceneView[%s]::_drawContent - getDrawData", getName().c_str());
        const DrawData& drawData = m_scene->_getDrawData();
        if (drawData || collectEmptyScene)
        {
            if (drawData && m_scene->hasDepthPolicies() && !this->supportsDepthGroups())
            {
                OMNIUI_LOG_ERROR_ONCE("DepthGroup requires a SceneView with scoped depth support; scene drawing skipped.");
                m_draw.reset();
                return false;
            }

            if (drawData && m_scene->hasDistanceFades() && !this->supportsDistanceFade())
            {
                OMNIUI_LOG_ERROR_ONCE("DistanceFadeGroup requires a SceneView with distance fade support; scene drawing skipped.");
                m_draw.reset();
                return false;
            }
            const auto& widths = m_scene->getWidthSpaceDrawBuffers();
            const bool worldWidths = std::any_of(widths.begin(), widths.end(), [](const WidthSpaceDrawBuffer& entry) {
                return entry.space == StrokeWidthSpace::eWorld;
            });
            const bool pixelDiameters = std::any_of(widths.begin(), widths.end(), [](const WidthSpaceDrawBuffer& entry) {
                return entry.space == StrokeWidthSpace::ePixelDiameter;
            });
            if ((worldWidths && !this->supportsWorldSpaceWidths()) ||
                (pixelDiameters && !this->supportsPixelDiameterWidths()))
            {
                OMNIUI_LOG_ERROR_ONCE("WidthSpaceGroup requires a SceneView supporting the requested stroke mode; scene drawing skipped.");
                m_draw.reset();
                return false;
            }

            if (!m_draw)
            {
                OMNIUI_PROFILE_VERBOSE_ZONE("SceneView[%s]::_drawContent - createDrawSystem", getName().c_str());

                // Lazily creating of the draw system
                m_draw = this->_createDrawSystem();
                // FIXME: Work around issue where draw data with textures is incomplete and results in white objects on first frame.
                return false;
            }

            clearDraw = false;
            {
                OMNIUI_PROFILE_VERBOSE_ZONE("SceneView[%s]::_drawContent - AbstractDrawSystem::beginFrame", getName().c_str());
                m_draw->beginFrame();
            }

            Matrix44 view;
            {
                OMNIUI_PROFILE_VERBOSE_ZONE("SceneView[%s]::_drawContent - view unlocked (draw)", getName().c_str());
                std::lock_guard<std::mutex> lock(m_prv->m_viewLock);
                OMNIUI_PROFILE_VERBOSE_ZONE("SceneView[%s]::_drawContent - view locked (draw)", getName().c_str());
                view = this->getView();
            }

            {
                OMNIUI_PROFILE_VERBOSE_ZONE("SceneView[%s]::_drawContent - AbstractDrawSystem::render", getName().c_str());
                m_draw->render(drawData.buffers, drawData.bufferCount, projection, view, width, height, dpiScale);
            }

            {
                OMNIUI_PROFILE_VERBOSE_ZONE("SceneView[%s]::_drawContent - AbstractDrawSystem::endFrame", getName().c_str());
                m_draw->endFrame();
            }
        }
    }

    // If nothing to draw, clear out the DrawSystem to release any resources in use.
    if (clearDraw)
    {
        m_draw.reset();
    }
    return !clearDraw;
}

bool SceneView::_collectOffscreenFrame(uint32_t width, uint32_t height, const Matrix44& projection,
                                      const Matrix44& view, float dpiScale)
{
    if (getParent())
        throw std::logic_error("Offscreen collection requires an unattached SceneView");
    if (!width || !height || !std::isfinite(dpiScale) || dpiScale <= 0.0f)
        throw std::invalid_argument("Offscreen collection requires positive dimensions and DPI scale");
    for (Matrix44::length_type column = 0; column != 4; ++column)
        for (Matrix44::length_type row = 0; row != 4; ++row)
            if (!std::isfinite(projection[column][row]) || !std::isfinite(view[column][row]))
                throw std::invalid_argument("Offscreen collection requires finite camera matrices");
    if (!isEnabled() || !m_scene)
        return false;
    if (m_scene->getSceneView() != this)
        throw std::logic_error("Offscreen collection requires a scene owned by this view");
    if (m_prv->m_offscreenProjection)
        throw std::logic_error("Offscreen collection cannot be reentered");
    struct CameraScope
    {
        SceneViewPrivate& state;
        CameraScope(SceneViewPrivate& state, const Matrix44& projection, const Matrix44& view) : state(state)
        {
            state.m_offscreenProjection = &projection;
            state.m_offscreenView = &view;
        }
        ~CameraScope()
        {
            state.m_offscreenProjection = state.m_offscreenView = nullptr;
        }
    } cameraScope(*m_prv, projection, view);

    // Dedicated capture scenes have no input. Use explicit dimensions for camera
    // scaling/billboards instead of querying an absent widget layout or ImGui frame.
    m_scene->preDrawContent(MouseInput{}, projection, view, width / dpiScale, height / dpiScale);
    try
    {
        m_scene->drawContent(projection, view);
    }
    catch (...)
    {
        m_scene->postDrawContent(projection, view);
        throw;
    }
    m_scene->postDrawContent(projection, view);
    if ((m_scene->hasDepthPolicies() && !supportsDepthGroups()) ||
        (m_scene->hasDistanceFades() && !supportsDistanceFade()))
        throw std::logic_error("Offscreen scene requires unsupported depth or fade policies");
    const auto& widths = m_scene->getWidthSpaceDrawBuffers();
    if (std::any_of(widths.begin(), widths.end(), [this](const WidthSpaceDrawBuffer& item) {
            return (item.space == StrokeWidthSpace::eWorld && !supportsWorldSpaceWidths()) ||
                   (item.space == StrokeWidthSpace::ePixelDiameter && !supportsPixelDiameterWidths());
        }))
        throw std::logic_error("Offscreen scene requires unsupported stroke widths");
    if (!m_draw)
    {
        // Preserve the existing first-collection texture initialization boundary.
        m_draw = _createDrawSystem();
        return false;
    }
    const DrawData& data = m_scene->_getDrawData();
    m_draw->beginFrame();
    m_draw->render(data.buffers, data.bufferCount, projection, view, float(width), float(height), dpiScale);
    m_draw->endFrame();
    // Empty scenes are deliberately collected too, so a removed overlay produces
    // a transparent result instead of reusing the preceding captured geometry.
    return true;
}

Matrix44 SceneView::getAmendedProjection() const
{
    if (m_prv->m_offscreenProjection)
        return *m_prv->m_offscreenProjection;
    float width = this->getComputedContentWidth();
    float height = this->getComputedContentHeight();

    auto aspectRatioPolicy = this->getAspectRatioPolicy();
    Float screenAspect = this->getScreenAspectRatio();
    bool needToFitScreen = true;
    if (screenAspect <= 0.0)
    {
        screenAspect = width / height;
        needToFitScreen = false;
    }

    // SceneView simulates the behavior of the Kit viewport where the rendered
    // image (screen) fits into the viewport (widget), and the camera has
    // multiple policies that modify the camera projection matrix's aspect ratio
    // to match it to the screen aspect ratio.
    // +-Widget-------------+
    // |                    |
    // +-Screen-------------+
    // |                    |
    // |    +----+          |
    // |   /    /|          |
    // |  +----+ |          |
    // |  |    | +          |
    // |  |    |/           |
    // |  +----+            |
    // |                    |
    // +--------------------+
    // |                    |
    // +--------------------+
    //
    // `CameraUtilConformedWindow` matches camera projection to screen (see drawings)
    // `if (needToFitScreen)` matches camera projection to the window (always fit)

    Matrix44 projection = CameraUtilConformedWindow(aspectRatioPolicy, screenAspect, m_projection);

    if (needToFitScreen)
    {
        Float widgetAspect = height / width;
        Float projectionAspect = projection[0][0] / projection[1][1];
        Float projectionWidgetRatio = projectionAspect / widgetAspect;

        if (projectionWidgetRatio > 1.0)
        {
            projection[0][0] = projection[1][1] * widgetAspect;
        }
        else
        {
            projection[1][1] = projection[0][0] / widgetAspect;
        }
    }

    return projection;
}

void SceneView::_dirtyHierarchy()
{
    auto scene = this->getScene();
    if (scene)
    {
        scene->dirtyHierarchy();
    }
}

SceneView::TextureOptions SceneView::getTextureOptions() const
{
    return {};
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
