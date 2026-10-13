/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

// The host-neutral scene Widget. The window that draws the Widget's content,
// its image and its input belong to the host, which registers a surface
// factory (omni/ui/platform/WidgetHost.h). Without one the Widget draws nothing.

#include <omni/ui/Frame.h>
#include <omni/ui/ImageProvider/ImageProvider.h>
#include <omni/ui/Workspace.h>
#include <omni/ui/platform/IUiSettings.h>
#include <omni/ui/platform/PlatformRegistry.h>
#include <omni/ui/platform/WidgetHost.h>
#include <omni/ui/scene/DrawList.h>
#include <omni/ui/scene/ImageHelper.h>
#include <omni/ui/scene/ShapeGesture.h>
#include <omni/ui/scene/Widget.h>

#include "RectangleData.h"

#include <algorithm>
#include <cmath>
#include <memory>
#include <vector>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

// frames to load images (default = 5)
constexpr char kFramesToDemand[] = "/exts/omni.ui.scene/widget/framesToDemand";
// frames to let regraw UI when mouse don't hover the widget (default = 5)
constexpr char kFramesToHover[] = "/exts/omni.ui.scene/widget/framesToHover";
constexpr int32_t kDefaultFrames = 5;

// Minimum resolution to avoid issues with under-sized textures
constexpr float kMinWidgetResolution = 32.0f;

namespace
{

/**
 * @brief Sends the mouse input of the Widget to the host surface.
 *
 * It's derived from ShapeGesture to have access to mouse input.
 */
class WidgetInputGesture : public ShapeGesture
{
public:
    explicit WidgetInputGesture(std::shared_ptr<omni::ui::WidgetSurface> surface) : m_surface{ std::move(surface) }
    {
    }

    // Reimplemented from ShapeGesture. Called every frame to preocess the
    // gesture. We get the mouse position from the gesture.
    void preProcess(const Matrix44& projection, const Matrix44& view) override
    {
        ShapeGesture::preProcess(projection, view);

        if (!m_surface || !m_surface->isValid())
        {
            return;
        }

        const auto* payload = reinterpret_cast<const Rectangle::RectangleGesturePayload*>(this->getGesturePayload());
        if (!payload)
        {
            return;
        }

        float s = static_cast<float>(payload->s);
        float t = 1.0f - static_cast<float>(payload->t);

        m_surface->mouseMove(s, t);

        // Support three mouse buttons. TODO: Scroll, etc...
        constexpr uint32_t buttonMask = (1 << 3) - 1;
        const auto& input = _getInput();
        uint32_t inputClicked = input.clicked & buttonMask;
        if (inputClicked)
        {
            m_surface->mouseButton(firstButton(inputClicked), true, s, t);
            m_sentClicked = inputClicked;
        }

        // missedRelease happens if:
        // 1. click without releasing
        // 2. hide sc.Widget
        // 3. release mouse - sc.Widget is hidden, eLeftButtonUp event is not sent to the host
        // 4. show sc.Widget
        // 5. next click on sc.Widget will not work because it still thinks the mouse button is down.
        uint32_t missedRelease = m_sentClicked & ~input.down;
        uint32_t inputReleased = (input.released & buttonMask) | missedRelease;
        if (inputReleased)
        {
            m_surface->mouseButton(firstButton(inputReleased), false, s, t);
            m_sentClicked = 0;
        }
    }

private:
    static uint32_t firstButton(uint32_t mask)
    {
        return (mask & 1 << 0) ? 0 : (mask & 1 << 1) ? 1 : 2;
    }

    std::shared_ptr<omni::ui::WidgetSurface> m_surface;
    uint32_t m_sentClicked = 0;
};

int32_t framesSetting(const char* path)
{
    auto* settings = omni::ui::PlatformRegistry::instance().settings();
    return settings ? settings->getInt(path, kDefaultFrames) : kDefaultFrames;
}

} // namespace

struct Widget::WidgetData : public Rectangle::RectangleData
{
    ~WidgetData() override = default;

    std::vector<Vector2> m_cachedUvs;

    // Widget resolution
    uint32_t m_imageWidth = 0;
    uint32_t m_imageHeight = 0;

    // How many frames since last invalidate
    uint32_t m_framesCounter = 0;

    // The host surface, and the gesture that sends it the mouse input
    std::shared_ptr<omni::ui::WidgetSurface> m_surface;
    std::shared_ptr<WidgetInputGesture> m_inputGesture;
};

template <typename T>
static void _scale(T& first, T& second, Float scale)
{
    T half = (first + second) * (Float).5;
    first = half + (first - half) * scale;
    second = half + (second - half) * scale;
}

Widget::Widget(Float width, Float height)
    : Rectangle(width, height, new WidgetData)
{
}

Widget::~Widget()
{
    auto& data = _getData<WidgetData>();
    if (data.m_surface)
    {
        data.m_surface->destroy(true);
        data.m_surface.reset();
    }
}

std::shared_ptr<omni::ui::Frame> Widget::getFrame()
{
    this->_validateImageProvider();

    auto& data = _getData<WidgetData>();
    return data.m_surface ? data.m_surface->frame() : std::shared_ptr<omni::ui::Frame>();
}

void Widget::invalidate()
{
    auto& data = _getData<WidgetData>();
    data.m_framesCounter = 0;

    if (data.m_surface)
    {
        data.m_surface->setFrozen(false);

        const auto& frame = data.m_surface->frame();
        if (frame && frame->hasBuildFn())
        {
            frame->rebuild();
        }
    }
}

void Widget::_preDrawContent(
    const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height)
{
    Rectangle::_preDrawContent(input, projection, view, width, height);
    this->forceDirty(DirtyReason::kDirtyReasonContentChanged);
}

void Widget::_drawContent(const Matrix44& projection, const Matrix44& view)
{
    this->_validateImageProvider();

    auto& data = _getData<WidgetData>();
    if (!data.m_surface)
    {
        return;
    }

    if (this->getUpdatePolicy() != UpdatePolicy::eOnDemand && this->getGestures().empty())
    {
        this->addGesture(data.m_inputGesture);
    }

    auto& gesturePayload = data.m_lastGesturePayload;
    const auto& frame = this->getFrame();
    float scale = this->getResolutionScale() / Workspace::getDpiScale();
    if (frame)
    {
        frame->setScale(scale);
    }
    float width = this->_computeResolutionWidth();
    float height = this->_computeResolutionHeight();

    bool frozen;
    switch (this->getUpdatePolicy())
    {
    case UpdatePolicy::eOnDemand:
        frozen = data.m_framesCounter >= uint32_t(framesSetting(kFramesToDemand));
        // Only update m_framesCounter when below frames-to wait to avoid roll-over
        if (!frozen)
        {
            ++data.m_framesCounter;
        }
        break;

    case UpdatePolicy::eOnMouseHovered: {
        const bool mouseIsInside = gesturePayload.s >= 0.0f && gesturePayload.s <= 1.0f &&
            gesturePayload.t >= 0.0f && gesturePayload.t <= 1.0f;
        if (mouseIsInside)
        {
            frozen = false;
            data.m_framesCounter = 0;
        }
        else
        {
            frozen = data.m_framesCounter >= uint32_t(framesSetting(kFramesToHover));
            // Only update m_framesCounter when below frames-to wait to avoid roll-over
            if (!frozen)
            {
                ++data.m_framesCounter;
            }
        }
    }
    break;

    case UpdatePolicy::eAlways:
    default:
        frozen = false;
        break;
    };

    // Init framebuffer if necessary and set input resulution
    data.m_surface->update(width, height, frozen);

    this->_rebuildCache();

    std::unique_ptr<void* []> imGuiTextures { new void*[data.m_cachedVertexCounts.size()] };
    std::fill(imGuiTextures.get(), imGuiTextures.get() + data.m_cachedVertexCounts.size(), nullptr);
    std::unique_ptr<void* []> resources { new void*[data.m_cachedVertexCounts.size()] };
    std::fill(resources.get(), resources.get() + data.m_cachedVertexCounts.size(), nullptr);

    omni::ui::ImageProvider* image = data.m_surface->image();
    void* textureGpuReference = image ? image->getImGuiReference() : nullptr;
    void* managedResource = image ? image->getManagedResource() : nullptr;
    auto textureSize = image ? image->getSize() : decltype(image->getSize()){};
    if (image && image->isReferenceValid() && textureSize.x != 0 && textureSize.y != 0)
    {
        if (textureSize.x != data.m_imageWidth || textureSize.y != data.m_imageHeight)
        {
            data.m_imageWidth = textureSize.x;
            data.m_imageHeight = textureSize.y;
            this->_dirtyCache();
        }

        std::fill(imGuiTextures.get(), imGuiTextures.get() + data.m_cachedVertexCounts.size(), textureGpuReference);
        std::fill(resources.get(), resources.get() + data.m_cachedVertexCounts.size(), managedResource);
    }

    auto drawList = this->_getDrawList();
    if (drawList)
    {
        drawList->addPolygonMesh(data.m_cachedPoints.data(), data.m_cachedColors.data(), data.m_cachedVertexIndices.data(),
                                 data.m_cachedVertexCounts.data(), data.m_cachedVertexCounts.size(),
                                 data.m_cachedUvs.data(), imGuiTextures.get(), resources.get());
    }
}

void Widget::_subdividePoly(size_t index, uint16_t levels)
{
    auto& data = _getData<WidgetData>();

    uint32_t i0 = data.m_cachedVertexIndices[index + 0];
    uint32_t i1 = data.m_cachedVertexIndices[index + 1];
    uint32_t i2 = data.m_cachedVertexIndices[index + 2];
    uint32_t i3 = data.m_cachedVertexIndices[index + 3];

    auto uv0 = data.m_cachedUvs[index + 0];
    auto uv1 = data.m_cachedUvs[index + 1];
    auto uv2 = data.m_cachedUvs[index + 2];
    auto uv3 = data.m_cachedUvs[index + 3];

    uint32_t nNew = static_cast<uint32_t>(data.m_cachedPoints.size());
    uint32_t m_cachedVertexIndicesSize = static_cast<uint32_t>(data.m_cachedVertexIndices.size());

    // Creating four points:
    // i0--0--i1
    // |   |   |
    // 1---4---2
    // |   |   |
    // i3--3--i2
    data.m_cachedPoints.push_back(0.5 * data.m_cachedPoints[i0] + 0.5 * data.m_cachedPoints[i1]); // New 0
    data.m_cachedPoints.push_back(0.5 * data.m_cachedPoints[i0] + 0.5 * data.m_cachedPoints[i3]); // New 1
    data.m_cachedPoints.push_back(0.5 * data.m_cachedPoints[i1] + 0.5 * data.m_cachedPoints[i2]); // New 2
    data.m_cachedPoints.push_back(0.5 * data.m_cachedPoints[i2] + 0.5 * data.m_cachedPoints[i3]); // New 3
    data.m_cachedPoints.push_back(0.5 * data.m_cachedPoints[nNew + 0] + 0.5 * data.m_cachedPoints[nNew + 3]); // New 4

    // Edit the old poly
    data.m_cachedVertexIndices[index + 1] = nNew + 0;
    data.m_cachedVertexIndices[index + 2] = nNew + 4;
    data.m_cachedVertexIndices[index + 3] = nNew + 1;
    data.m_cachedUvs[index + 1] = 0.5 * uv0 + 0.5 * uv1;
    data.m_cachedUvs[index + 2] = 0.25 * uv0 + 0.25 * uv1 + 0.25 * uv2 + 0.25 * uv3;
    data.m_cachedUvs[index + 3] = 0.5 * uv0 + 0.5 * uv3;

    // Create three more polys
    data.m_cachedVertexIndices.push_back(nNew + 0);
    data.m_cachedVertexIndices.push_back(i1);
    data.m_cachedVertexIndices.push_back(nNew + 2);
    data.m_cachedVertexIndices.push_back(nNew + 4);
    data.m_cachedUvs.emplace_back(0.5 * uv0 + 0.5 * uv1);
    data.m_cachedUvs.emplace_back(uv1);
    data.m_cachedUvs.emplace_back(0.5 * uv1 + 0.5 * uv2);
    data.m_cachedUvs.emplace_back(0.25 * uv0 + 0.25 * uv1 + 0.25 * uv2 + 0.25 * uv3);

    data.m_cachedVertexIndices.push_back(nNew + 1);
    data.m_cachedVertexIndices.push_back(nNew + 4);
    data.m_cachedVertexIndices.push_back(nNew + 3);
    data.m_cachedVertexIndices.push_back(i3);
    data.m_cachedUvs.emplace_back(0.5 * uv0 + 0.5 * uv3);
    data.m_cachedUvs.emplace_back(0.25 * uv0 + 0.25 * uv1 + 0.25 * uv2 + 0.25 * uv3);
    data.m_cachedUvs.emplace_back(0.5 * uv2 + 0.5 * uv3);
    data.m_cachedUvs.emplace_back(uv3);

    data.m_cachedVertexIndices.push_back(nNew + 4);
    data.m_cachedVertexIndices.push_back(nNew + 2);
    data.m_cachedVertexIndices.push_back(i2);
    data.m_cachedVertexIndices.push_back(nNew + 3);
    data.m_cachedUvs.emplace_back(0.25 * uv0 + 0.25 * uv1 + 0.25 * uv2 + 0.25 * uv3);
    data.m_cachedUvs.emplace_back(0.5 * uv1 + 0.5 * uv2);
    data.m_cachedUvs.emplace_back(uv2);
    data.m_cachedUvs.emplace_back(0.5 * uv2 + 0.5 * uv3);

    if (levels == 0)
    {
        return;
    }

    this->_subdividePoly(index, levels - 1);
    this->_subdividePoly(m_cachedVertexIndicesSize + 0, levels - 1);
    this->_subdividePoly(m_cachedVertexIndicesSize + 4, levels - 1);
    this->_subdividePoly(m_cachedVertexIndicesSize + 8, levels - 1);
}

void Widget::_rebuildCache()
{
    auto& data = _getData<WidgetData>();
    if (!data.m_cacheIsDirty)
    {
        return;
    }

    // Build Rectangle
    Rectangle::_rebuildCache();

    // Override vertex count
    data.m_cachedVertexCounts[0] = 4;

    // Build UVs
    data.m_cachedUvs.clear();
    _ensureCapacity(data.m_cachedUvs, 4);

    float width = this->_computeResolutionWidth();
    float height = this->_computeResolutionHeight();

    Float rectangleAspect = height / width;
    Float imageAspect = data.m_imageWidth > 0 && data.m_imageHeight > 0 ?
                            static_cast<Float>(data.m_imageHeight) / static_cast<Float>(data.m_imageWidth) :
                            (Float)1.0;

    Float widthMin = 0.0;
    Float widthMax = 1.0;
    Float heightMin = 0.0;
    Float heightMax = 1.0;

    if (data.m_imageWidth > 0 && data.m_imageHeight > 0)
    {
        if (this->getFillPolicy() == FillPolicy::ePreserveAspectCrop)
        {
            if (rectangleAspect < imageAspect)
            {
                // Scale UV height
                Float aspect = rectangleAspect / imageAspect;
                _scale(heightMin, heightMax, aspect);
            }
            else
            {
                // Scale UV width
                Float aspect = imageAspect / rectangleAspect;
                _scale(widthMin, widthMax, aspect);
            }
        }
        else if (this->getFillPolicy() == FillPolicy::ePreserveAspectFit)
        {
            if (rectangleAspect < imageAspect)
            {
                // Scale width
                Float aspect = rectangleAspect / imageAspect;
                switch (this->getAxis())
                {
                case 0:
                    _scale(data.m_cachedPoints[0].y, data.m_cachedPoints[2].y, aspect);
                    _scale(data.m_cachedPoints[1].y, data.m_cachedPoints[3].y, aspect);

                    break;
                default:
                    _scale(data.m_cachedPoints[0].x, data.m_cachedPoints[2].x, aspect);
                    _scale(data.m_cachedPoints[1].x, data.m_cachedPoints[3].x, aspect);

                    break;
                }
            }
            else
            {
                // Scale height
                Float aspect = imageAspect / rectangleAspect;
                switch (this->getAxis())
                {
                case 0:
                case 1:
                    _scale(data.m_cachedPoints[0].z, data.m_cachedPoints[2].z, aspect);
                    _scale(data.m_cachedPoints[1].z, data.m_cachedPoints[3].z, aspect);

                    break;
                default:
                    _scale(data.m_cachedPoints[0].y, data.m_cachedPoints[2].y, aspect);
                    _scale(data.m_cachedPoints[1].y, data.m_cachedPoints[3].y, aspect);

                    break;
                };
            }
        }
    }

    data.m_cachedUvs.emplace_back(widthMax, heightMin);
    data.m_cachedUvs.emplace_back(widthMax, heightMax);
    data.m_cachedUvs.emplace_back(widthMin, heightMax);
    data.m_cachedUvs.emplace_back(widthMin, heightMin);

    // Subdivide the polygon 3 times, so we have 4^3=64 polys. We need it to fix
    // afifine UV mapping. We don't have access to the backend shaders, so the
    // only way to fix it is subdivision.
    // TODO: m_cachedVertexCounts.reserve, m_cachedPoints.reserve, etc...
    constexpr uint16_t subdivisionLevels = 3;
    if (subdivisionLevels)
    {
        this->_subdividePoly(0, subdivisionLevels - 1);

        data.m_cachedVertexCounts.resize(static_cast<size_t>(std::pow(4, subdivisionLevels)));
        std::fill(data.m_cachedVertexCounts.begin(), data.m_cachedVertexCounts.end(), 4);

        size_t size = data.m_cachedVertexIndices.size();

        data.m_cachedColors.resize(size);
        std::fill(data.m_cachedColors.begin(), data.m_cachedColors.end(), this->getColor());
    }
}

void Widget::_validateImageProvider()
{
    auto& data = _getData<WidgetData>();
    if (data.m_surface)
    {
        return;
    }

    auto factory = omni::ui::getWidgetHost();
    if (!factory)
    {
        return;
    }

    data.m_surface = factory(this->_computeResolutionWidth(), this->_computeResolutionHeight(), ImageHelper::getTextureOptions());
    if (data.m_surface)
    {
        data.m_inputGesture = std::make_shared<WidgetInputGesture>(data.m_surface);
    }
}

float Widget::_computeResolutionWidth() const
{
    // Minimum size of 32 to avoid issues with under-sized textures
    return std::max(this->getResolutionWidth() ? static_cast<float>(this->getResolutionWidth()) :
                                                 static_cast<float>(this->getWidth()),
                    kMinWidgetResolution);
}

float Widget::_computeResolutionHeight() const
{
    // Minimum size of 32 to avoid issues with under-sized textures
    return std::max(this->getResolutionHeight() ? static_cast<float>(this->getResolutionHeight()) :
                                                  static_cast<float>(this->getHeight()),
                    kMinWidgetResolution);
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
