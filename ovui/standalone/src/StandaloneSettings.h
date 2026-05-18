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

#include <omni/ui/platform/IUiSettings.h>

#include <mutex>
#include <string>
#include <unordered_map>
#include <variant>
#include <vector>

namespace omni {
namespace ui {
namespace standalone {

/// In-memory IUiSettings implementation for the standalone backend.
/// Stores settings in a map of string -> variant and fires synchronous
/// change notifications on set.
class StandaloneSettings final : public IUiSettings
{
public:
    StandaloneSettings() = default;
    ~StandaloneSettings() override = default;

    // -- Getters --
    bool getBool(const char* path, bool defaultVal) override;
    int32_t getInt(const char* path, int32_t defaultVal) override;
    float getFloat(const char* path, float defaultVal) override;
    std::string getString(const char* path, const char* defaultVal) override;

    // -- Setters --
    void setBool(const char* path, bool value) override;
    void setInt(const char* path, int32_t value) override;
    void setFloat(const char* path, float value) override;
    void setString(const char* path, const char* value) override;

    // -- Defaults (set only if not already present) --
    void setDefaultBool(const char* path, bool value) override;
    void setDefaultInt(const char* path, int32_t value) override;
    void setDefaultFloat(const char* path, float value) override;
    void setDefaultString(const char* path, const char* value) override;

    // -- Subscriptions --
    SettingsSubscriptionId subscribe(const char* path, ChangeCallback callback) override;
    void unsubscribe(SettingsSubscriptionId id) override;

private:
    using Value = std::variant<bool, int32_t, float, std::string>;

    void fireCallbacks(const char* path);

    std::mutex m_mutex;
    std::unordered_map<std::string, Value> m_values;

    struct Subscription
    {
        SettingsSubscriptionId id;
        std::string pathPrefix;
        ChangeCallback callback;
    };
    SettingsSubscriptionId m_nextSubId = 1;
    std::vector<Subscription> m_subscriptions;
};

} // namespace standalone
} // namespace ui
} // namespace omni
