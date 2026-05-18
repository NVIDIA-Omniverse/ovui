/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include <cstdint>
#include <functional>
#include <memory>
#include <string>

namespace omni {
namespace ui {

using SettingsSubscriptionId = uint64_t;

/// Abstract settings interface for omni.ui.
/// Each backend provides its own concrete implementation:
/// KitSettingsAdapter in the Kit adapter layer, or a simple in-memory
/// map in the standalone backend.
class IUiSettings
{
public:
    virtual ~IUiSettings() = default;

    virtual bool getBool(const char* path, bool defaultVal = false) = 0;
    virtual int32_t getInt(const char* path, int32_t defaultVal = 0) = 0;
    virtual float getFloat(const char* path, float defaultVal = 0.0f) = 0;
    virtual std::string getString(const char* path, const char* defaultVal = "") = 0;

    virtual void setBool(const char* path, bool value) = 0;
    virtual void setInt(const char* path, int32_t value) = 0;
    virtual void setFloat(const char* path, float value) = 0;
    virtual void setString(const char* path, const char* value) = 0;

    virtual void setDefaultBool(const char* path, bool value) = 0;
    virtual void setDefaultInt(const char* path, int32_t value) = 0;
    virtual void setDefaultFloat(const char* path, float value) = 0;
    virtual void setDefaultString(const char* path, const char* value) = 0;

    using ChangeCallback = std::function<void(const char* path)>;
    virtual SettingsSubscriptionId subscribe(const char* path, ChangeCallback callback) = 0;
    virtual void unsubscribe(SettingsSubscriptionId id) = 0;
};

} // namespace ui
} // namespace omni
