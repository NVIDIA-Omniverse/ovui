/*
 * SPDX-FileCopyrightText: Copyright (c) 2022-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "ByteImageProvider.h"

#include <string>

namespace omni
{
namespace ui
{

class OMNIUI_CLASS_API DynamicTextureProvider : public ByteImageProvider
{
public:
    /**
     * @brief Construct DynamicTextureProvider.
     * @param textureName Name of dynamic texture which will be updated from setBytesData.
    */
    OMNIUI_API
    DynamicTextureProvider(const std::string& textureName);

    OMNIUI_API
    virtual ~DynamicTextureProvider() override;

protected:
    OMNIUI_API
    bool _setManagedResource(GpuResource* gpuResource) override;

    OMNIUI_API
    bool mergeTextureOptions(TextureOptions& textureOptions) const override;

    std::string m_textureUri;
};

}
}
