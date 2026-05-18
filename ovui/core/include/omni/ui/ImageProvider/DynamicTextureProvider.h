/*
 * SPDX-FileCopyrightText: Copyright (c) 2022-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
