/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
#include "Callback.h"
#include "Property.h"
#include "RasterPolicy.h"

#include <memory>

OMNIUI_NAMESPACE_OPEN_SCOPE

class Widget;

struct RasterHelperPrivate;

/**
 * @brief The "RasterHelper" class is used to manage the draw lists or raster
 * images. This class is responsible for rasterizing (or baking) the UI, which
 * involves adding information about widgets to the cache. Once the UI has been
 * baked, the draw list cache can be used to quickly re-render the UI without
 * having to iterate over the widgets again. This is useful because it allows
 * the UI to be rendered more efficiently, especially in cases where the widgets
 * have not changed since the last time the UI was rendered. The "RasterHelper"
 * class provides methods for modifying the cache and rendering the UI from the
 * cached information.
 */
class OMNIUI_CLASS_API RasterHelper : private CallbackHelper<RasterHelper>
{
public:
    OMNIUI_API
    virtual ~RasterHelper();

    /**
     * @brief Determine how the content of the frame should be rasterized.
     */
    OMNIUI_PROPERTY(RasterPolicy,
                    rasterPolicy,
                    DEFAULT,
                    RasterPolicy::eNever,
                    READ,
                    getRasterPolicy,
                    WRITE,
                    setRasterPolicy,
                    PROTECTED,
                    NOTIFY,
                    _setRasterPolicyChangedFn);

    /**
     * @brief This method regenerates the raster image of the widget, even if
     * the widget's content has not changed. This can be used with both the
     * eOnDemand and eAuto raster policies, and is used to update the content
     * displayed in the widget. Note that this operation may be
     * resource-intensive, and should be used sparingly.
     */
    OMNIUI_API
    void invalidateRaster();

protected:
    friend class MenuDelegate;

    /**
     * @brief Constructor
     */
    OMNIUI_API
    RasterHelper();

    /**
     * @brief Should be called by the widget in init time.
     */
    void _rasterHelperInit(Widget& widget);

    /**
     * @brief Should be called by the widget in destroy time.
     */
    void _rasterHelperDestroy();

    OMNIUI_API
    bool _rasterHelperBegin(float posX, float posY, float width, float height);

    OMNIUI_API
    void _rasterHelperEnd();

    OMNIUI_API
    void _rasterHelperSetDirtyDrawList();

    OMNIUI_API
    void _rasterHelperSetDirtyLod();

    OMNIUI_API
    void _rasterHelperSuspendRasterization(bool stopRasterization);

    OMNIUI_API
    bool _isInRasterWindow() const;

private:
    void _captureRaster(float originX, float originY);

    void _drawRaster(float originX, float originY) const;

    bool _isDirtyDrawList() const;

    std::unique_ptr<RasterHelperPrivate> m_prv;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
