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

#include "ImageProvider.h"

#include <mutex>
#include <string>

namespace omni
{
namespace ui
{

class OMNIUI_CLASS_API VectorImageProvider : public ImageProvider
{
public:
    OMNIUI_API
    VectorImageProvider(std::string url = {});

    OMNIUI_API
    ~VectorImageProvider();

    /**
     * @brief Sets the vector image URL. Asset loading doesn't happen immediately, but rather is started the next time
     * widget is visible, in prepareDraw call.
     */
    OMNIUI_API
    virtual void setSourceUrl(const char* url);

    /**
     * @brief Returns vector image URL.
     */
    OMNIUI_API
    virtual std::string getSourceUrl() const;

    /**
     * @brief This function needs to be called every frame to make sure asset loading is moving forward, and resources
     * are properly allocated.
     */
    OMNIUI_API
    void prepareDraw(float widgetWidth, float widgetHeight) override;

    /**
     * @brief Sets the maximum number of mip map levels allowed.
     */
    OMNIUI_API
    virtual void setMaxMipLevels(size_t maxMipLevels);

    /**
     * @brief Returns the maximum number of mip map levels allowed.
     */
    OMNIUI_API
    virtual size_t getMaxMipLevels() const;

protected:
    std::string m_sourceVectorUrl;
    bool m_sourceVectorUrlChanged = false;
    mutable std::mutex m_sourceVectorUrlMutex;
    size_t m_maxMipLevels = 3;
    mutable std::mutex m_maxMipLevelsMutex;
    std::string m_cacheKey;
};

}
}
