/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#define OMNIUI_PYBIND_DOC_RasterHelper                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     \
    "The \"RasterHelper\" class is used to manage the draw lists or raster images. This class is responsible for rasterizing (or baking) the UI, which involves adding information about widgets to the cache. Once the UI has been baked, the draw list cache can be used to quickly re-render the UI without having to iterate over the widgets again. This is useful because it allows the UI to be rendered more efficiently, especially in cases where the widgets have not changed since the last time the UI was rendered. The \"RasterHelper\" class provides methods for modifying the cache and rendering the UI from the cached information.\n" \
    "\n"


#define OMNIUI_PYBIND_DOC_RasterHelper_rasterPolicy "Determine how the content of the frame should be rasterized.\n"


#define OMNIUI_PYBIND_DOC_RasterHelper_invalidateRaster "This method regenerates the raster image of the widget, even if the widget's content has not changed. This can be used with both the eOnDemand and eAuto raster policies, and is used to update the content displayed in the widget. Note that this operation may be resource-intensive, and should be used sparingly.\n"


#define OMNIUI_PYBIND_DOC_RasterHelper_RasterHelper "Constructor.\n"
